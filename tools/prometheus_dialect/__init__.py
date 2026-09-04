"""SQLAlchemy dialect ``prometheus`` (driver ``rest``).

URI forms:
    prometheus://host:port              -> http://host:port
    prometheus+https://host:port        -> https://host:port
    prometheus://host:port/db           -> http://host:port/db   (path prefix)

Introspection is implemented here (schema names, table names == Prometheus
metric names, columns == labels + timestamp + value) so Superset can use it
through the standard SQLAlchemy inspector.
"""

from __future__ import annotations

from sqlalchemy import types
from sqlalchemy.engine.default import DefaultDialect

from . import dbapi

__all__ = ["PrometheusDialect"]


class PrometheusDialect(DefaultDialect):
    name = "prometheus"
    driver = "rest"

    supports_statement_cache = False
    supports_alter = False
    supports_comments = False
    supports_default_values = False
    supports_empty_insert = False
    supports_identity_columns = False
    supports_sequences = False
    supports_sane_rowcount = False
    supports_sane_multi_rowcount = False
    supports_multivalues_insert = False
    supports_native_boolean = True
    supports_unicode_statements = True
    supports_unicode_binds = True
    default_paramstyle = "qmark"

    @classmethod
    def dbapi(cls):
        return dbapi

    def create_connect_args(self, url):
        use_https = "+https" in (url.drivername or "") or str(url.query.get("ssl", "")).lower() in ("1", "true")
        host = url.host or "localhost"
        base = f"{'https' if use_https else 'http'}://{host}"
        if url.port:
            base += f":{url.port}"
        if url.database:
            base += f"/{url.database}"
        return ([], {"base_url": base})

    def do_ping(self, dbapi_connection) -> bool:
        return dbapi_connection.ping()

    # -- introspection ----------------------------------------------------
    def get_schema_names(self, connection, **kw):
        return ["default"]

    def _pc(self, connection):
        raw = getattr(connection, "connection", connection)
        pc = getattr(raw, "_pc", None)
        if pc is None:
            raise dbapi.PrometheusError("Unable to reach Prometheus client from connection")
        return pc

    def get_table_names(self, connection, schema=None, **kw):
        pc = self._pc(connection)
        return sorted(set(pc.all_metrics()))

    def get_view_names(self, connection, schema=None, **kw):
        # Prometheus has no views
        return []

    def get_indexes(self, connection, table_name, schema=None, **kw):
        return []

    def get_pk_constraint(self, connection, table_name, schema=None, **kw):
        return {"constrained_columns": [], "name": None}

    def get_primary_keys(self, connection, table_name, schema=None, **kw):
        return []

    def get_foreign_keys(self, connection, table_name, schema=None, **kw):
        return []

    def get_unique_constraints(self, connection, table_name, schema=None, **kw):
        return []

    def get_check_constraints(self, connection, table_name, schema=None, **kw):
        return []

    def get_table_comment(self, connection, table_name, schema=None, **kw):
        return {"text": None}

    def has_table(self, connection, table_name, schema=None, **kw):
        if table_name in self.get_table_names(connection, schema=schema):
            return True
        # HPC patch: allow arbitrary PromQL expressions as virtual tables
        try:
            self.get_columns(connection, table_name, schema=schema)
            return True
        except Exception:
            return False

    def get_columns(self, connection, table_name, schema=None, **kw):
        pc = self._pc(connection)
        labels: set[str] = set()
        if str(table_name).strip().lower() == "alerts":
            # alerts 虚拟表：/api/v1/alerts（含 description/summary）
            try:
                from .dbapi import fetch_alerts

                for lbl, _t, _v in fetch_alerts(pc):
                    labels.update(lbl.keys())
            except Exception:
                pass
        else:
            try:
                for item in pc.custom_query(table_name) or []:
                    if isinstance(item, dict):
                        labels.update((item.get("metric") or {}).keys())
            except Exception:
                pass  # metric may be absent or query may fail; still expose base columns

        cols = [
            {
                "name": "timestamp",
                "type": types.DateTime(),
                "nullable": True,
                "default": None,
                "autoincrement": False,
                "comment": "sample timestamp (epoch seconds)",
            }
        ]
        for label in sorted(labels):
            cols.append(
                {
                    "name": label,
                    "type": types.String(),
                    "nullable": True,
                    "default": None,
                    "autoincrement": False,
                    "comment": "prometheus label",
                }
            )
        cols.append(
            {
                "name": "value",
                "type": types.Float(),
                "nullable": True,
                "default": None,
                "autoincrement": False,
                "comment": "metric value",
            }
        )
        return cols
