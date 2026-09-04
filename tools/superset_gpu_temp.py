"""Superset 创建 GPU 高温(>85℃) 卡明细图表（数据集 + 图表 + 加入 dashboard 5）

依赖：v_gpu_temp 视图已在 MySQL 建好（见下方 SQL）
用法：python3 superset_gpu_temp.py [base_url]
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
VIEW = "v_gpu_temp"

CHART_NAME = "GPU 高温(>85℃) 卡明细"

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
    q = '{"filters":[{"col":"table_name","opr":"eq","value":"%s"}]}' % name
    data = api("/dataset/?q=" + requests.utils.quote(q))
    return (data["result"] or [None])[0]


def find_chart(name):
    q = '{"filters":[{"col":"slice_name","opr":"eq","value":"%s"}]}' % name
    data = api("/chart/?q=" + requests.utils.quote(q))
    return (data["result"] or [None])[0]


def main():
    tok = api("/security/login", "POST", json={
        "username": USER, "password": PWD, "provider": "db", "refresh": True})["access_token"]
    AUTH["Authorization"] = "Bearer " + tok
    global CSRF
    CSRF = api("/security/csrf_token/")["result"]
    print("CSRF token 获取成功")

    ds = find_dataset(VIEW)
    if ds:
        ds_id = ds["id"]
        print("数据集已存在: %s (id=%s)" % (VIEW, ds_id))
    else:
        ds = api("/dataset/", "POST", json={
            "database": DB_ID, "schema": "gpu_timer", "table_name": VIEW})
        ds_id = ds["id"]
        print("数据集已创建: %s (id=%s)" % (VIEW, ds_id))
    try:
        api("/dataset/%s/refresh" % ds_id, "POST")
        print("数据集列已刷新")
    except SystemExit:
        print("refresh endpoint 不可用，跳过（创建时已自动同步列）")

    params = {
        "datasource": "%s__table" % ds_id,
        "viz_type": "table",
        "slice_name": CHART_NAME,
        "time_range": "Last day",
        "granularity_sqla": "ts",
        "time_grain_sqla": "P1D",
        "include_time": False,
        "groupby": ["ip", "gpu_temp_hot_idx", "gpu_temp_hot_uuid"],
        "metrics": [
            {"expressionType": "SIMPLE", "column": {"column_name": "gpu_temp_max"},
             "aggregate": "MAX", "hasCustomLabel": True, "label": "最高温度(℃)"},
            {"expressionType": "SQL",
             "sqlExpression": "SUM(gpu_temp_max > 85) * 5",
             "hasCustomLabel": True, "label": "超温分钟"},
            {"expressionType": "SIMPLE", "column": {"column_name": "id"},
             "aggregate": "COUNT", "hasCustomLabel": True, "label": "超温采样数"},
        ],
        "order_by_cols": [["最高温度(℃)", False]],
        "order_desc": True,
        "row_limit": 50,
        "page_length": 50,
        "adhoc_filters": [
            {"expressionType": "SIMPLE", "clause": "WHERE",
             "subject": "gpu_temp_max", "operator": ">", "comparator": 85,
             "sqlExpression": None}
        ],
        "show_cell_bars": False,
        "align_pn": False,
        "table_timestamp_format": "smart_date",
    }
    body = {
        "datasource_id": ds_id,
        "datasource_type": "table",
        "viz_type": "table",
        "slice_name": CHART_NAME,
        "params": json.dumps(params),
        "dashboards": [DASHBOARD_ID],
    }
    exist = find_chart(CHART_NAME)
    if exist:
        api("/chart/%s" % exist["id"], "PUT", json=body)
        print("图表已更新: %s (id=%s)" % (CHART_NAME, exist["id"]))
    else:
        ch = api("/chart/", "POST", json=body)
        print("图表已创建: %s (id=%s)" % (CHART_NAME, ch["id"]))

    print("完成: %s/superset/dashboard/%s/" % (ROOT, DASHBOARD_ID))


if __name__ == "__main__":
    main()
