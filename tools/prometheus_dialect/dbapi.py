"""DBAPI-2.0-ish layer for Prometheus backed by prometheus-api-client.

Executes "SQL" in two modes:
  * simple ``SELECT [cols] FROM <metric> [WHERE label='v' ...] [LIMIT n]``
    -> translated to a PromQL instant query
  * anything else -> the whole statement is treated as a PromQL query
    (e.g. ``rate(node_cpu_seconds_total[5m])``, ``up``, ``topk(5, up)``)

Rows are always shaped as ``(timestamp, <labels...>, value)`` for
``SELECT *``, or as the projected columns otherwise.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence, Tuple

from prometheus_api_client import PrometheusConnect

import ast as _ast
import operator as _op

__all__ = [
    "connect",
    "Connection",
    "Cursor",
    "Error",
    "Warning",
    "InterfaceError",
    "DatabaseError",
    "DataError",
    "OperationalError",
    "IntegrityError",
    "InternalError",
    "ProgrammingError",
    "NotSupportedError",
    "apilevel",
    "threadsafety",
    "paramstyle",
]

apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"


class PrometheusError(Exception):
    """Raised when a query cannot be executed against Prometheus."""


# Standard DBAPI exception hierarchy (SQLAlchemy inspects these).
class Warning(Exception):  # noqa: A001
    pass


class Error(PrometheusError):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


def connect(base_url: str) -> "Connection":
    return Connection(base_url)


def _strip_ident(ident: str) -> str:
    return ident.strip().strip('"`\'')


def _last_part(expr: str) -> str:
    """Take the last dotted component of a (possibly quoted) identifier.

    Handles ``"default"."node_load1"`` / ``"node_load1"`` / ``node_load1``
    / backtick forms -> ``node_load1``. Dots inside quotes are respected.
    """
    expr = expr.strip()
    parts: list[str] = []
    for chunk in expr.split("."):
        parts.append(_strip_ident(chunk))
    return parts[-1]


_SELECT_RE = re.compile(
    r"^\s*select\s+(.+?)\s+from\s+(.+?)(?:\s+((?:where|group\s+by|having|order\s+by|limit)\b.*))?$",
    re.IGNORECASE | re.DOTALL,
)
_COND_RE = re.compile(r"\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s*=\s*['\"]([^'\"]*)['\"]")
_LIMIT_RE = re.compile(r"limit\s+(\d+)", re.IGNORECASE)
_GROUP_BY_RE = re.compile(
    r"\bgroup\s+by\s+(.+?)(?=\s+(?:having|order\s+by|limit)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_TS_BOUND_RE = re.compile(
    r"\"?(?:timestamp|__time|time|__timestamp)\"?\s*(>=|<=|>|<)\s*"
    r"('(?:[^']*)'|\"(?:[^\"]*)\"|\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


_TS_FMTS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _parse_ts_value(raw: str) -> Optional[float]:
    """Parse a timestamp filter value into epoch seconds.

    Accepts epoch numbers (``1720000000``) and datetime strings
    (``'2026-08-25 08:30:00'``, with optional timezone suffix). Naive
    datetimes are interpreted in the process-local timezone (the
    container runs with TZ=Asia/Shanghai, matching Superset's rendering
    of the time filter).
    """
    s = raw.strip().strip("'\"")
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        v = float(s)
        if v > 1e12:  # millisecond epoch
            v /= 1000.0
        return v
    txt = s.strip()
    tz: Optional[timezone] = None
    m = re.search(r"([+-]\d{2}:?\d{2}|Z)$", txt, re.IGNORECASE)
    if m:
        tzs = m.group(1)
        txt = txt[: m.start()].strip()
        if tzs.upper() == "Z":
            tz = timezone.utc
        else:
            sign = 1 if tzs[0] == "+" else -1
            tzs = tzs[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(tzs[:2]), minutes=int(tzs[2:])))
    dt: Optional[datetime] = None
    for fmt in _TS_FMTS:
        try:
            dt = datetime.strptime(txt, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        if tz is None:
            return dt.timestamp()  # process-local time (container = Asia/Shanghai)
        dt = dt.replace(tzinfo=tz)
    return dt.timestamp()
_AGG_RE = re.compile(r"^(?:max|min|avg|sum|count)\s*\((.+)\)$", re.IGNORECASE)

_TIME_COLS = ("timestamp", "time", "__time", "__timestamp")
_VALUE_COLS = ("value", "__value")

# --- 聚合算术组合支持（2026-08-26）---
# metric 表达式可以是纯聚合，也可以是聚合的算术组合，例如：
#   SUM(value, __name__='node_memory_MemTotal_bytes')
#     - SUM(value, __name__='node_memory_MemAvailable_bytes')
# 每个聚合调用可带可选的标签谓词 label='value'，只对该子集聚合。
_AGG_CALL_RE = re.compile(
    r"(max|min|avg|sum|count)\s*\(([^()]*)\)\s*(?:filter\s*\(\s*where\s+([^()]*)\))?",
    re.IGNORECASE,
)
_PRED_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]([^'\"]*)['\"]")

_BINOPS = {
    _ast.Add: _op.add,
    _ast.Sub: _op.sub,
    _ast.Mult: _op.mul,
    _ast.Div: _op.truediv,
    _ast.Mod: _op.mod,
    _ast.Pow: _op.pow,
}


def _safe_arith(s: str) -> Optional[float]:
    """Evaluate a numeric expression: numbers, + - * / % ** and parens.
    Aggregate calls must already be substituted with numeric results."""
    try:
        tree = _ast.parse(s, mode="eval")
    except SyntaxError:
        return None

    def ev(node):
        if isinstance(node, _ast.Expression):
            return ev(node.body)
        if isinstance(node, _ast.Constant):
            return node.value
        if isinstance(node, _ast.BinOp) and type(node.op) in _BINOPS:
            left = ev(node.left)
            right = ev(node.right)
            if left is None or right is None:
                return None
            try:
                return _BINOPS[type(node.op)](left, right)
            except ZeroDivisionError:
                return None
        if isinstance(node, _ast.UnaryOp) and isinstance(node.op, _ast.USub):
            return -ev(node.operand)
        return None

    try:
        return ev(tree)
    except Exception:
        return None


def _agg_value(op: str, inner: str, points, filter_where: Optional[str] = None) -> Optional[float]:
    """Evaluate one aggregate call over points.

    inner may carry label predicates: ``value, __name__='x'`` (legacy), or
    the call may be followed by a SQL FILTER clause: ``SUM(value) FILTER
    (WHERE __name__ = 'x')``. Only points matching all predicates are
    aggregated (COUNT counts matching points). Mirrors the pure-aggregate
    semantics used in _apply_aggregation.
    """
    parts = _split_top_level(inner)
    target = parts[0].strip().strip('"`\'')
    preds: list[tuple[str, str]] = []
    rest: list[str] = []
    for p in parts[1:]:
        pm = _PRED_RE.match(p.strip())
        if pm:
            preds.append((pm.group(1), pm.group(2)))
        else:
            rest.append(p)
    if target.lower().startswith("distinct") and rest:
        # COUNT(DISTINCT a, b)：逗号后面的非谓词部分属于 distinct 列列表
        target = target + "," + ",".join(rest)
    if filter_where:
        preds.extend((pm.group(1), pm.group(2)) for pm in _PRED_RE.finditer(filter_where))
    pts = (
        [(l, t, v) for l, t, v in points if all(l.get(k) == val for k, val in preds)]
        if preds
        else points
    )
    t = target.lower()
    if op == "count":
        if t.startswith("distinct"):
            dcols = [
                c.strip().strip('"`\'')
                for c in target[len("distinct"):].split(",")
                if c.strip()
            ]
            seen = set()
            for lbl, _t, _v in pts:
                key = tuple(lbl.get(c) for c in dcols)
                if all(k not in (None, "") for k in key):
                    seen.add(key)
            return float(len(seen))
        if t in _VALUE_COLS or "value" in t or t in ("", "*"):
            return float(len(pts))
        return float(sum(1 for lbl, _t, _v in pts if lbl.get(t) not in (None, "")))
    vals = [_v for _l, _t, _v in pts]
    if op == "sum":
        return float(sum(vals))
    if op == "avg":
        return float(sum(vals) / len(vals)) if vals else None
    if op == "max":
        return float(max(vals)) if vals else None
    if op == "min":
        return float(min(vals)) if vals else None
    return None




def fetch_alerts(pc):
    """Fetch active alerts from Prometheus /api/v1/alerts.

    Returns a list of (labels, ts, value) points. Annotations description /
    summary are merged into labels so SQL can project/filter them; the
    alert state is exposed as the ``alertstate`` label.
    """
    import json as _json
    import urllib.request as _ur

    url = pc.url.rstrip("/") + "/api/v1/alerts"
    with _ur.urlopen(url, timeout=30) as r:
        data = _json.load(r)
    out: list = []
    now = time.time()
    for a in (data.get("data") or {}).get("alerts", []) or []:
        labels = dict(a.get("labels") or {})
        labels["alertstate"] = a.get("state", "")
        ann = a.get("annotations") or {}
        if ann.get("description"):
            labels["description"] = ann["description"]
        if ann.get("summary"):
            labels["summary"] = ann["summary"]
        out.append((labels, now, 1.0))
    return out


def _alerts_filtered(fetched: list, selector: str) -> list:
    """Apply the ``alerts{label="v",...}`` selector conditions."""
    m = re.match(r"alerts(\{.*\})?", selector.strip(), re.IGNORECASE)
    conds = _COND_RE.findall(m.group(1)) if m and m.group(1) else []
    if not conds:
        return fetched
    return [
        (l, t, v)
        for l, t, v in fetched
        if all(l.get(k) == val for k, val in conds)
    ]


def _simple_agg_match(expr: str):
    """Return the _AGG_RE match when expr is a SIMPLE pure aggregate
    (no label predicates like __name__='x' inside); None otherwise."""
    m = _AGG_RE.match(expr.strip())
    if m and not _PRED_RE.search(m.group(1)):
        return m
    return None


def _eval_metric_expr(expr: str, points) -> Optional[float]:
    """Evaluate an aggregate metric expression over points.

    Supports pure aggregates (``SUM(value)``) and arithmetic combinations
    of aggregates with optional label predicates (e.g. ``1 - SUM(value,
    __name__='x') / SUM(value, __name__='y')``). Returns None when the
    expression contains no aggregate call or cannot be evaluated.
    """
    if not _AGG_CALL_RE.search(expr):
        return None

    def repl(m: re.Match) -> str:
        v = _agg_value(m.group(1).lower(), m.group(2), points, m.group(3))
        return "None" if v is None else repr(v)

    return _safe_arith(_AGG_CALL_RE.sub(repl, expr))


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on a separator, ignoring separators inside quotes/parens."""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    quote: Optional[str] = None
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            cur.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _norm_col(expr: str) -> tuple:
    """Split a select-list item into (lookup_col, out_col).

    ``SELECT col AS alias`` -> lookup uses the REAL column (left of AS) to
    read the Prometheus label, but the RESULT column name must be the alias
    (right of AS) -- pandas/Superset address columns by the alias (e.g.
    ``column_values`` from values_for_column).
    """
    expr = expr.strip()
    parts = re.split(r"\bas\b", expr, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) > 1:
        lookup = _last_part(parts[0])
        out = _last_part(parts[1])
    else:
        lookup = out = _last_part(parts[0])
    return lookup, out


_SIMPLE_METRIC_RE = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]*$")


def _parse_select(
    sql: str,
) -> Optional[Tuple[str, Optional[list[str]], Optional[int], Optional[float], Optional[float], Optional[list[tuple]], Optional[list[str]]]]:
    """Translate a simple SELECT into (promql, columns, limit, from_ts, to_ts, post_filter, group_cols).

    columns is None for ``SELECT *``. from_ts/to_ts are epoch seconds parsed
    from ``WHERE timestamp >= x AND timestamp <= y`` (used for range queries).
    post_filter is a list of (label, value) pairs to apply AFTER the PromQL
    query returns (used when the "table" is a complex PromQL expression where
    appending ``{label="v"}`` would be a syntax error). group_cols is the
    list of GROUP BY columns (labels or timestamp-ish columns), or None.
    Returns None when the statement is not a simple SELECT (caller then
    treats the text as raw PromQL).
    """
    m = _SELECT_RE.match(sql)
    if not m:
        return None
    cols_part, metric, tail = m.group(1), m.group(2), (m.group(3) or "")
    # Superset filter-value queries use SELECT DISTINCT ...; drop the
    # keyword so DISTINCT job resolves to the label "job" (and ALL too).
    cols_part = re.sub(r"^\s*(?:distinct|all)\s+", "", cols_part, flags=re.IGNORECASE)
    # strip table alias: FROM "up" AS t -> "up"
    metric = re.split(r"\bas\b", metric, maxsplit=1, flags=re.IGNORECASE)[0]
    selector = _last_part(metric)

    # tail holds the WHERE-clause body (the WHERE keyword itself was
    # consumed by the outer regex) plus optional GROUP BY / LIMIT / ORDER BY.
    conditions: list[tuple[str, str]] = []
    for cm in _COND_RE.finditer(tail):
        label, val = cm.group(1), cm.group(2)
        if label.lower() == "__name__":
            selector = val  # allow __name__='up'
        else:
            conditions.append((label, val))

    post_filter: Optional[list[tuple[str, str]]] = None
    if conditions:
        if _SIMPLE_METRIC_RE.match(selector):
            # Plain metric name: "up{label='v'}" is valid PromQL.
            conds = ",".join('%s="%s"' % (l, v) for l, v in conditions)
            selector = "%s{%s}" % (selector, conds)
        else:
            # Complex expression (virtual table): can't append {..} to it.
            # Keep the conditions and filter rows after the query returns.
            post_filter = conditions

    # timestamp bounds -> Prometheus range query
    from_ts: Optional[float] = None
    to_ts: Optional[float] = None
    for tm in _TS_BOUND_RE.finditer(tail):
        op, raw = tm.group(1), tm.group(2)
        val = _parse_ts_value(raw)
        if val is None:
            continue
        if op in (">", ">="):
            from_ts = val if from_ts is None else max(from_ts, val)
        else:
            to_ts = val if to_ts is None else min(to_ts, val)

    limit_m = _LIMIT_RE.search(tail)
    limit = int(limit_m.group(1)) if limit_m else None

    # GROUP BY columns: SQL grouping is not expressible in PromQL, so we
    # remember the columns here and aggregate the fetched rows in Python
    # (see _apply_group_by).
    group_cols: Optional[list[str]] = None
    gm = _GROUP_BY_RE.search(tail)
    if gm:
        group_cols = [
            _last_part(gc) for gc in _split_top_level(gm.group(1)) if gc.strip()
        ]

    if cols_part.strip() == "*":
        columns = None
    else:
        columns = [_norm_col(c) for c in _split_top_level(cols_part) if c.strip()]
        if not columns:
            columns = None
    return selector, columns, limit, from_ts, to_ts, post_filter, group_cols


def _build_row(labels: dict, columns: Optional[list], ts: float, val: float) -> tuple:
    if columns is None:
        return (ts, *[labels.get(k) for k in sorted(labels)], val)
    return tuple(_resolve_col(c[0], labels, ts, val) for c in columns)


def _resolve_col(c: str, labels: dict, ts: float, val: float):
    """Resolve a projected column to a value (handles aggregates)."""
    cl = c.lower().strip()
    if cl in _VALUE_COLS:
        return val
    if cl in _TIME_COLS:
        return ts
    m = _AGG_RE.match(cl)
    if m:
        inner = m.group(1).strip().strip('"`\'').lower()
        if inner in _VALUE_COLS or "value" in inner:
            return val
        if inner in ("", "*"):
            return 1.0
        return labels.get(m.group(1).strip().strip('"`\''))
    return labels.get(c)


def _apply_aggregation(points, columns):
    """Collapse to a single aggregate row when the select-list is purely
    aggregate (no GROUP BY). points: list of (labels, ts, val).

    Returns the collapsed row list, or None when the query mixes plain
    columns with aggregates (not a valid aggregate query without GROUP BY)
    or has no aggregates at all -- caller keeps its normal row building.
    """
    if not columns:
        return None
    aggs = [_AGG_RE.match(c[0]) for c in columns]
    if not any(aggs) or any(a is None or _PRED_RE.search(a.group(1)) for a in aggs):
        # 纯聚合（无谓词）以外的情形：select 列表全是聚合表达式时
        # 统一用 _eval_metric_expr 折叠为单行（支持谓词/算术组合）
        if columns and all(_AGG_CALL_RE.search(c[0]) for c in columns):
            return [tuple(_eval_metric_expr(c[0], points) for c in columns)]
        return None
    vals = [v for _l, _t, v in points]
    n = len(points)
    out = []
    for (lookup, _out), m in zip(columns, aggs):
        op = m.group(0).split("(", 1)[0].lower()
        inner = m.group(1).strip().strip('"`\'').lower()
        if op == "count":
            if inner.startswith("distinct"):
                # COUNT(DISTINCT a, b) -> count unique (a,b) label tuples
                dcols = [
                    c.strip().strip('"`\'')
                    for c in inner[len("distinct"):].split(",")
                    if c.strip()
                ]
                seen = set()
                for lbl, _t, _v in points:
                    key = tuple(lbl.get(c) for c in dcols)
                    if all(k not in (None, "") for k in key):
                        seen.add(key)
                out.append(float(len(seen)))
            elif inner in _VALUE_COLS or "value" in inner or inner in ("", "*"):
                out.append(float(n))
            else:  # count(label) -> non-empty label count
                out.append(float(sum(1 for lbl, _t, _v in points if lbl.get(inner) not in (None, ""))))
        elif op in ("sum", "avg", "max", "min"):
            if inner in _VALUE_COLS or "value" in inner:
                if op == "sum":
                    out.append(float(sum(vals)))
                elif op == "avg":
                    out.append(float(sum(vals) / n) if n else None)
                elif op == "max":
                    out.append(float(max(vals)) if vals else None)
                else:
                    out.append(float(min(vals)) if vals else None)
            else:
                out.append(None)
        else:
            out.append(None)
    return [tuple(out)]


def _apply_group_by(points, columns, group_cols):
    """Implement SQL GROUP BY in Python.

    PromQL has no SQL-style GROUP BY, so instead of translating it we fetch
    the per-series rows and aggregate them here: rows are grouped by the
    GROUP BY columns (labels, or the sample timestamp for timestamp-ish
    columns), and each aggregate select column (count/sum/avg/max/min) is
    computed over the values in its group. Non-aggregate columns keep the
    first-seen value of the group (typically the group column itself).

    points: list of (labels, ts, val). Returns the grouped rows, or None
    when there is nothing to aggregate (caller keeps per-series rows).
    """
    if not columns or not group_cols:
        return None
    groups: dict = {}
    order: list = []
    # 复合聚合列（非简单纯聚合但含聚合调用）需要整组点集统一计算
    compound_cols = [
        i for i, (c, _o) in enumerate(columns)
        if _AGG_CALL_RE.search(c) and not _simple_agg_match(c)
    ]
    need_points = bool(compound_cols)
    gpoints: dict = {} if need_points else None
    for labels, ts, val in points:
        key = []
        for gc in group_cols:
            gcl = gc.lower().strip()
            if gcl in _TIME_COLS:
                key.append(ts)
            elif gcl in _VALUE_COLS:
                key.append(val)
            else:
                key.append(labels.get(gc))
        key = tuple(key)
        g = groups.get(key)
        if g is None:
            g = {}
            groups[key] = g
            order.append(key)
        if need_points:
            gpoints.setdefault(key, []).append((labels, ts, val))
        for i, (lookup, _out) in enumerate(columns):
            if i in compound_cols:
                continue  # 组内点收集后统一计算
            lm = _AGG_RE.match(lookup.strip())
            if lm is None:
                # plain column: keep the first-seen value (e.g. the label
                # the group is keyed on, or the sample timestamp)
                plain = lookup.strip().strip('"`\'')
                pcl = plain.lower().strip()
                if pcl in _TIME_COLS:
                    g.setdefault(i, ts)
                elif pcl in _VALUE_COLS:
                    g.setdefault(i, val)
                else:
                    g.setdefault(i, labels.get(plain))
                continue
            op = lm.group(0).split("(", 1)[0].lower()
            inner = lm.group(1).strip().strip('"`\'').lower()
            if op == "count":
                if inner.startswith("distinct"):
                    # COUNT(DISTINCT a, b) within the group
                    dcols = [
                        c.strip().strip('"`\'')
                        for c in inner[len("distinct"):].split(",")
                        if c.strip()
                    ]
                    skey = "__distinct_%d" % i
                    seen = g.get(skey)
                    if seen is None:
                        seen = set()
                        g[skey] = seen
                    key = tuple(labels.get(c) for c in dcols)
                    if all(k not in (None, "") for k in key):
                        seen.add(key)
                    g[i] = float(len(seen))
                elif inner in _VALUE_COLS or "value" in inner or inner in ("", "*"):
                    g[i] = g.get(i, 0.0) + 1.0
                elif labels.get(inner) not in (None, ""):
                    g[i] = g.get(i, 0.0) + 1.0
            elif op in ("sum", "avg", "max", "min"):
                if inner in _VALUE_COLS or "value" in inner:
                    if op == "sum":
                        g[i] = g.get(i, 0.0) + val
                    elif op == "avg":
                        s, n = g.get(i, (0.0, 0))
                        g[i] = (s + val, n + 1)
                    elif op == "max":
                        cur = g.get(i)
                        g[i] = val if cur is None else max(cur, val)
                    elif op == "min":
                        cur = g.get(i)
                        g[i] = val if cur is None else min(cur, val)
                else:
                    g.setdefault(i, None)
            else:
                g.setdefault(i, None)
    rows = []
    for key in order:
        g = groups[key]
        row = []
        for i, (_lookup, _out) in enumerate(columns):
            if i in compound_cols:
                pts = gpoints.get(key) or []
                row.append(_eval_metric_expr(_lookup, pts))
                continue
            v = g.get(i)
            if isinstance(v, tuple):  # avg accumulator (sum, n)
                s, n = v
                v = s / n if n else None
            row.append(v)
        rows.append(tuple(row))
    return rows


def _desc(names: Iterable[str]) -> list[tuple]:
    return [(n, None, None, None, None, None, None) for n in names]


def _pick_step(start_ts: float, end_ts: float) -> int:
    """Pick a nice Prometheus step that yields ~200 samples."""
    span = max(60.0, end_ts - start_ts)
    target = span / 200
    for nice in (15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400):
        if target <= nice:
            return nice
    return int(target)


class Connection:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._pc = PrometheusConnect(url=base_url, disable_ssl=True)

    def close(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def cursor(self) -> "Cursor":
        return Cursor(self._pc)

    def ping(self) -> bool:
        try:
            return bool(self._pc.check_prometheus_connection())
        except Exception:
            return False

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Cursor:
    def __init__(self, pc: PrometheusConnect):
        self._pc = pc
        self.description: Optional[list[tuple]] = None
        self.rowcount = -1
        self.arraysize = 1
        self._rows: list[tuple] = []
        self._idx = 0

    # -- result handling -------------------------------------------------
    def _set_result(self, description: list[tuple], rows: list[tuple]) -> None:
        self.description = description
        self._rows = rows
        self.rowcount = len(rows)
        self._idx = 0

    # -- execution -------------------------------------------------------
    def execute(self, sql: str, parameters: Optional[Sequence] = None) -> "Cursor":
        text = (sql or "").strip()
        if not text:
            self._set_result(_desc(["result"]), [])
            return self
        if re.fullmatch(r"select\s+1", text, re.IGNORECASE):
            # Make connection tests honest: actually reach the Prometheus API.
            try:
                ok = bool(self._pc.check_prometheus_connection())
            except Exception as ex:
                raise PrometheusError(
                    f"Cannot reach Prometheus at {self._pc.url}: {ex}"
                ) from ex
            if not ok:
                raise PrometheusError(
                    f"Cannot reach Prometheus at {self._pc.url}"
                )
            self._set_result(_desc(["1"]), [(1,)])
            return self
        if re.fullmatch(r"show\s+metrics", text, re.IGNORECASE):
            names = sorted(set(self._pc.all_metrics()))
            self._set_result(_desc(["metric"]), [(n,) for n in names])
            return self

        parsed = _parse_select(text)
        if parsed is not None:
            promql, columns, limit, from_ts, to_ts, post_filter, group_cols = parsed
            distinct = bool(re.search(r"\bdistinct\b", text, re.IGNORECASE))
        else:
            promql, columns, limit, from_ts, to_ts, post_filter, group_cols = (
                text,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            distinct = False

        alerts_sel = (
            re.fullmatch(r"alerts(?:\{.*\})?", promql.strip(), re.IGNORECASE)
            if promql and promql.strip()
            else None
        )
        try:
            if alerts_sel:
                # alerts 虚拟表：/api/v1/alerts（含 annotations description/summary）
                result = [
                    {"metric": lbl, "value": [t, str(v)]}
                    for lbl, t, v in _alerts_filtered(fetch_alerts(self._pc), promql)
                ]
            elif from_ts is not None or to_ts is not None:
                # time-filtered -> Prometheus range query (real time series)
                now = time.time()
                start = datetime.fromtimestamp(
                    from_ts if from_ts is not None else now - 3600, tz=timezone.utc
                )
                end = datetime.fromtimestamp(
                    to_ts if to_ts is not None else now, tz=timezone.utc
                )
                if end <= start:
                    end = start + timedelta(seconds=60)
                step = _pick_step(start.timestamp(), end.timestamp())
                result = self._pc.custom_query_range(
                    promql, start, end, f"{step}s"
                )
            else:
                result = self._pc.custom_query(promql)
        except Exception as ex:  # network / HTTP errors
            raise PrometheusError(f"Prometheus query failed: {ex}") from ex

        if not isinstance(result, list):
            raise PrometheusError(f"Unexpected Prometheus response: {result!r}")

        # Matrix results (range queries like ``up[5m]``) carry "values";
        # instant vectors carry "value".
        is_matrix = any(isinstance(item, dict) and "values" in item for item in result[:5])

        labels_union: set[str] = set()
        for item in result:
            if isinstance(item, dict):
                labels_union.update((item.get("metric") or {}).keys())

        rows: list[tuple] = []
        points: list[tuple] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            labels = item.get("metric") or {}
            if post_filter and not all(labels.get(l) == v for l, v in post_filter):
                continue
            if is_matrix:
                for ts, val in item.get("values") or []:
                    v = float(val)
                    points.append((labels, float(ts), v))
                    rows.append(_build_row(labels, columns, float(ts), v))
            else:
                ts, val = item.get("value") or [0, "0"]
                v = float(val)
                points.append((labels, float(ts), v))
                rows.append(_build_row(labels, columns, float(ts), v))

        if group_cols:
            # SQL GROUP BY -> aggregate the fetched rows in Python (PromQL
            # cannot express GROUP BY directly).
            agg_rows = _apply_group_by(points, columns, group_cols)
        else:
            agg_rows = _apply_aggregation(points, columns)
        if agg_rows is not None:
            rows = agg_rows

        if distinct:
            # SELECT DISTINCT -> drop duplicate rows (keep first occurrence)
            seen: set = set()
            out: list = []
            for r in rows:
                if r not in seen:
                    seen.add(r)
                    out.append(r)
            rows = out

        if limit is not None:
            rows = rows[:limit]

        if columns is None:
            description = _desc(["timestamp", *sorted(labels_union), "value"])
        else:
            description = _desc([out for _lookup, out in columns])
        self._set_result(description, rows)
        return self

    def executemany(self, sql: str, seq_of_parameters) -> "Cursor":
        for params in seq_of_parameters:
            self.execute(sql, params)
        return self

    # -- fetching --------------------------------------------------------
    def fetchone(self) -> Optional[tuple]:
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return row

    def fetchmany(self, size: Optional[int] = None) -> list[tuple]:
        size = size if size is not None else self.arraysize
        rows = self._rows[self._idx : self._idx + size]
        self._idx += len(rows)
        return rows

    def fetchall(self) -> list[tuple]:
        rows = self._rows[self._idx :]
        self._idx = len(self._rows)
        return rows

    def close(self) -> None:
        pass

    def setinputsizes(self, *args) -> None:
        pass

    def setoutputsize(self, size, column=None) -> None:
        pass

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row