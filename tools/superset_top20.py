"""Superset 自动创建/更新 CPU/GPU TOP20 报表（数据集 + 图表 + 加入 dashboard 5）

依赖：v_util_full 视图已在 MySQL 建好（deploy_top20.sh 步骤 5 完成）
用法：python3 superset_top20.py [base_url]
"""
import json
import os
import sys
import requests

ROOT = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUPERSET_BASE", "http://<SUPERSET_HOST>:8088")).rstrip("/")
BASE = ROOT + "/api/v1"
USER = os.environ.get("SUPERSET_USER", "admin")
PWD = os.environ.get("SUPERSET_PWD", "")
if not PWD:
    sys.exit("请通过环境变量提供凭据: SUPERSET_PWD（可选 SUPERSET_BASE / SUPERSET_USER）")
DASHBOARD_ID = 5          # 「GPU 服务器在线计时」
DB_ID = 2                 # gpu_timer MySQL
VIEW = "v_util_full"

CHARTS = [
    {
        "name": "CPU 日均负载 TOP20",
        "groupby": ["ip"],
        "metrics": [
            {"expressionType": "SIMPLE", "column": {"column_name": "cpu_load1"},
             "aggregate": "AVG", "hasCustomLabel": True, "label": "日均负载"},
            {"expressionType": "SQL", "sqlExpression": "AVG(cpu_load1)/AVG(cpu_cores)",
             "hasCustomLabel": True, "label": "每核负载"},
            {"expressionType": "SIMPLE", "column": {"column_name": "cpu_load1"},
             "aggregate": "MAX", "hasCustomLabel": True, "label": "峰值负载"},
            {"expressionType": "SIMPLE", "column": {"column_name": "id"},
             "aggregate": "COUNT", "hasCustomLabel": True, "label": "采样数"},
        ],
        "order_by": "日均负载",
    },
    {
        "name": "GPU 日均利用率 TOP20",
        "groupby": ["ip"],
        "metrics": [
            {"expressionType": "SIMPLE", "column": {"column_name": "gpu_util_avg"},
             "aggregate": "AVG", "hasCustomLabel": True, "label": "日均利用率"},
            {"expressionType": "SIMPLE", "column": {"column_name": "gpu_util_max"},
             "aggregate": "MAX", "hasCustomLabel": True, "label": "峰值利用率"},
            {"expressionType": "SIMPLE", "column": {"column_name": "id"},
             "aggregate": "COUNT", "hasCustomLabel": True, "label": "采样数"},
        ],
        "order_by": "日均利用率",
    },
]


AUTH = {"Authorization": ""}
CSRF = ""
S = requests.Session()


def api(path, method="GET", **kw):
    kw.setdefault("timeout", 20)
    headers = dict(AUTH)
    if method in ("POST", "PUT", "DELETE"):
        headers["X-CSRFToken"] = CSRF
    kw["headers"] = headers
    r = S.request(method, BASE + path, **kw)
    if r.status_code >= 400:
        print("API %s %s -> %s: %s" % (method, path, r.status_code, r.text[:300]))
        sys.exit(1)
    return r.json()


def find_dataset(name):
    data = api("/dataset/?q=" + requests.utils.quote('{"filters":[{"col":"table_name","opr":"eq","value":"%s"}]}' % name))
    return (data["result"] or [None])[0]


def find_chart(name):
    data = api("/chart/?q=" + requests.utils.quote('{"filters":[{"col":"slice_name","opr":"eq","value":"%s"}]}' % name))
    return (data["result"] or [None])[0]


def main():
    tok = api("/security/login", "POST", json={
        "username": USER, "password": PWD, "provider": "db", "refresh": True})["access_token"]
    AUTH["Authorization"] = "Bearer " + tok
    global CSRF
    CSRF = api("/security/csrf_token/")["result"]
    print("CSRF token 获取成功")

    # 1. 数据集 v_util_full
    ds = find_dataset(VIEW)
    if ds:
        ds_id = ds["id"]
        print("数据集已存在: v_util_full (id=%s)" % ds_id)
    else:
        ds = api("/dataset/", "POST", json={
            "database": DB_ID, "schema": "gpu_timer", "table_name": VIEW})
        ds_id = ds["id"]
        print("数据集已创建: v_util_full (id=%s)" % ds_id)
    # 同步列：superset 5.0 创建表数据集时已自动 fetch 列；refresh endpoint 可能不存在，容错跳过
    try:
        api("/dataset/%s/refresh" % ds_id, "POST")
        print("数据集列已刷新")
    except SystemExit:
        print("refresh endpoint 不可用，跳过（创建时已自动同步列）")

    # 2. 图表
    for c in CHARTS:
        exist = find_chart(c["name"])
        params = {
            "datasource": "%s__table" % ds_id,
            "viz_type": "table",
            "slice_name": c["name"],
            "time_range": "Last day",
            "granularity_sqla": "ts",
            "time_grain_sqla": "P1D",
            "include_time": True,
            "groupby": c["groupby"],
            "metrics": c["metrics"],
            "order_by_cols": [[c["order_by"], False]],
            "order_desc": True,
            "row_limit": 20,
            "page_length": 20,
            "adhoc_filters": [],
            "show_cell_bars": False,
            "align_pn": False,
            "table_timestamp_format": "smart_date",
        }
        body = {
            "datasource_id": ds_id,
            "datasource_type": "table",
            "viz_type": "table",
            "slice_name": c["name"],
            "params": json.dumps(params),
            "dashboards": [DASHBOARD_ID],
        }
        if exist:
            api("/chart/%s" % exist["id"], "PUT", json=body)
            print("图表已更新: %s (id=%s)" % (c["name"], exist["id"]))
        else:
            ch = api("/chart/", "POST", json=body)
            print("图表已创建: %s (id=%s)" % (c["name"], ch["id"]))

    print("完成: %s/superset/dashboard/%s/" % (ROOT, DASHBOARD_ID))


if __name__ == "__main__":
    main()
