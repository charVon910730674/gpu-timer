"""142 Superset(Prometheus 数据源)：节点在线统计数据集 + 3 Metrics + table 图表

数据源：DB id=1 Prometheus (prometheus://<PROM_HOST>:9090)
数据集：table_name = "up{job!=''}"（PromQL 即表名；= up 全量 target）
  ⚠️ 坑：表名内不能有 `.`（_last_part 按点切分，up{job=~'.+'} 会被劈坏）
  ⚠️ 坑：不能用 "up"（已存在 dataset id=1，冲突）
Metrics（dialect 只支持纯 count/sum/avg/max/min 聚合，勿用 CASE WHEN/CAST/算术）:
  - 总的节点数 total_nodes : COUNT(*)          （series 数 = target 数）
  - 在线节点数 online_nodes : SUM(value)        （up∈{0,1}，求和=up==1 数量）
  - 在线率 online_rate : AVG(value)             （0~1 小数，chart 用 d3NumberFormat .1% 显示）
图表：viz_type=table（现有类型），结构与 chart 44 (fc计算节点) 一致
用法：python3 superset_prom_node_summary.py [base_url]
"""
import json
import os
import sys
import requests

ROOT = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUPERSET_BASE", "http://127.0.0.1:8088")).rstrip("/")
BASE = ROOT + "/api/v1"
USER = os.environ.get("SUPERSET_USER", "admin")
PWD = os.environ.get("SUPERSET_PWD", "")
if not PWD:
    sys.exit("请通过环境变量提供凭据: SUPERSET_PWD（可选 SUPERSET_BASE / SUPERSET_USER）")
DB_ID = 1                     # Prometheus
DS_TABLE = "up{job!=''}"
CHART_NAME = "节点在线统计 (Prometheus)"

METRICS = [
    {"metric_name": "total_nodes", "verbose_name": "总的节点数",
     "expression": "COUNT(*)", "description": "监控 target 总数", "extra": "{}", "d3format": None},
    {"metric_name": "online_nodes", "verbose_name": "在线节点数",
     "expression": "SUM(value)", "description": "up==1 的节点数", "extra": "{}", "d3format": None},
    {"metric_name": "online_rate", "verbose_name": "在线率",
     "expression": "AVG(value)", "description": "在线占比(0~1)", "extra": "{}", "d3format": ".1%"},
]

# chart 内 metric 用 SQL adhoc（与 chart 44 一致的结构；无引号，不受吞引号 bug 影响）
CHART_METRICS = [
    {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "总的节点数", "hasCustomLabel": True},
    {"expressionType": "SQL", "sqlExpression": "SUM(value)", "label": "在线节点数", "hasCustomLabel": True},
    {"expressionType": "SQL", "sqlExpression": "AVG(value)", "label": "在线率", "hasCustomLabel": True},
]

AUTH = {"Authorization": ""}
CSRF = ""
S = requests.Session()


def api(path, method="GET", **kw):
    kw.setdefault("timeout", 30)
    headers = dict(AUTH)
    if method in ("POST", "PUT", "DELETE"):
        headers["X-CSRFToken"] = CSRF
    kw["headers"] = headers
    r = S.request(method, BASE + path, **kw)
    if r.status_code >= 400:
        print("API %s %s -> %s: %s" % (method, path, r.status_code, r.text[:400]))
        sys.exit(1)
    return r.json()


def find_dataset(name):
    data = api("/dataset/?q=" + requests.utils.quote(
        '{"filters":[{"col":"table_name","opr":"eq","value":"%s"}]}' % name))
    return (data["result"] or [None])[0]


def find_chart(name):
    data = api("/chart/?q=" + requests.utils.quote(
        '{"filters":[{"col":"slice_name","opr":"eq","value":"%s"}]}' % name))
    return (data["result"] or [None])[0]


def main():
    tok = api("/security/login", "POST", json={
        "username": USER, "password": PWD, "provider": "db", "refresh": True})["access_token"]
    AUTH["Authorization"] = "Bearer " + tok
    global CSRF
    CSRF = api("/security/csrf_token/")["result"]
    print("auth OK")

    # 1. 数据集（表名即 PromQL）
    ds = find_dataset(DS_TABLE)
    if ds:
        ds_id = ds["id"]
        print("数据集已存在: %s (id=%s)" % (DS_TABLE, ds_id))
    else:
        ds = api("/dataset/", "POST", json={
            "database": DB_ID, "schema": "default", "table_name": DS_TABLE})
        ds_id = ds["id"]
        print("数据集已创建: %s (id=%s)" % (DS_TABLE, ds_id))

    # 2. Metrics（PUT 会整体替换；已存在同名则跳过，避免 422）
    cur = api("/dataset/%s" % ds_id)
    existing = {mt["metric_name"] for mt in cur["result"].get("metrics", [])}
    missing = [m for m in METRICS if m["metric_name"] not in existing]
    if missing:
        api("/dataset/%s" % ds_id, "PUT", json={
            "metrics": [{k: v for k, v in m.items() if v is not None} for m in missing]})
        print("metrics 已写入: %s" % ", ".join(m["metric_name"] for m in missing))
    else:
        print("metrics 已存在，跳过")

    # 3. 验证查询（sqllab execute，尽力而为）
    try:
        r = S.post(BASE + "/sqllab/execute/", headers={
            "Authorization": AUTH["Authorization"], "X-CSRFToken": CSRF,
            "Content-Type": "application/json"},
            data=json.dumps({"database_id": DB_ID, "sql":
                'SELECT COUNT(*) AS total_nodes, SUM(value) AS online_nodes, '
                'AVG(value) AS online_rate FROM "%s"' % DS_TABLE}),
            timeout=30)
        if r.status_code == 200:
            print("查询验证:", json.dumps(r.json().get("data", {}), ensure_ascii=False)[:300])
        else:
            print("sqllab execute 不可用(%s)，跳过查询验证" % r.status_code)
    except Exception as e:
        print("sqllab execute 异常，跳过:", e)

    # 4. 图表（table，现有类型）
    ch = find_chart(CHART_NAME)
    params = {
        "datasource": "%s__table" % ds_id,
        "viz_type": "table",
        "slice_name": CHART_NAME,
        "time_range": "No filter",
        "granularity_sqla": None,
        "groupby": [],
        "columns": [],
        "metrics": CHART_METRICS,
        "adhoc_filters": [],
        "order_by_cols": [],
        "row_limit": 10,
        "page_length": 10,
        "include_search": False,
        "show_cell_bars": False,
        "table_timestamp_format": "smart_date",
        "column_config": {"在线率": {"d3NumberFormat": ".1%", "d3Format": ".1%"}},
    }
    body = {
        "datasource_id": ds_id,
        "datasource_type": "table",
        "viz_type": "table",
        "slice_name": CHART_NAME,
        "params": json.dumps(params),
    }
    if ch:
        api("/chart/%s" % ch["id"], "PUT", json=body)
        print("图表已更新: %s (id=%s)" % (CHART_NAME, ch["id"]))
    else:
        c = api("/chart/", "POST", json=body)
        print("图表已创建: %s (id=%s)" % (CHART_NAME, c["id"]))

    # 5. 最终确认
    d = api("/dataset/%s" % ds_id)
    print("最终 Metrics:")
    for mt in d["result"].get("metrics", []):
        print("  -", mt.get("verbose_name"), "|", mt.get("metric_name"), "|", mt.get("expression"))
    print("完成: http://localhost:8088/superset/dataset/%s/  chart: http://localhost:8088/superset/explore/?form_data_key=" % ds_id)


if __name__ == "__main__":
    main()
