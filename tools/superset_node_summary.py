"""142 Superset：新建/更新节点在线统计数据集（fc_nodes_summary）+ 3 个 Metrics

Metrics:
  - 总的节点数 total_nodes : COUNT(node_name)
  - 在线节点数 online_nodes : SUM(CASE WHEN status='online' THEN 1 ELSE 0 END)
  - 在线率 online_rate : ROUND(... * 100.0 / COUNT(*), 2)  (%)

坑（已固化处理）:
  - Superset 5.0 无 /api/v1/metric/ 端点 → 用 PUT /dataset/{id} 传 metrics 数组
  - 该 PUT 会把表达式中的单引号 'online' 吞掉（存成非法 SQL）
    → 建完后必须 docker exec 直写 sql_metrics 表修正 expression

用法（在 142 上执行）: python3 superset_node_summary.py [base_url]
"""
import json
import os
import subprocess
import sys
import requests

ROOT = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUPERSET_BASE", "http://127.0.0.1:8088")).rstrip("/")
BASE = ROOT + "/api/v1"
USER = os.environ.get("SUPERSET_USER", "admin")
PWD = os.environ.get("SUPERSET_PWD", "")
if not PWD:
    sys.exit("请通过环境变量提供凭据: SUPERSET_PWD（可选 SUPERSET_BASE / SUPERSET_USER）")
DB_ID = 2                     # HPC资源中心(演示数据) sqlite
DS_NAME = "fc_nodes_summary"
DS_SQL = "SELECT node_name, status FROM fc_nodes"

METRICS = [
    # metric_name, verbose_name, api_expr(PUT 用，会被吞引号), expr(最终正确表达式)
    ("total_nodes", "总的节点数", "COUNT(node_name)", "COUNT(node_name)"),
    ("online_nodes", "在线节点数",
     "SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END)",
     "SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END)"),
    ("online_rate", "在线率",
     "ROUND(SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)",
     "ROUND(SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)"),
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


def main():
    tok = api("/security/login", "POST", json={
        "username": USER, "password": PWD, "provider": "db", "refresh": True})["access_token"]
    AUTH["Authorization"] = "Bearer " + tok
    global CSRF
    CSRF = api("/security/csrf_token/")["result"]
    print("auth OK")

    # 1. 数据集（幂等）
    data = api("/dataset/?q=" + requests.utils.quote(
        '{"filters":[{"col":"table_name","opr":"eq","value":"%s"}]}' % DS_NAME))
    if data["result"]:
        ds_id = data["result"][0]["id"]
        print("数据集已存在: %s (id=%s)" % (DS_NAME, ds_id))
    else:
        ds = api("/dataset/", "POST", json={
            "database": DB_ID, "schema": "main", "table_name": DS_NAME, "sql": DS_SQL})
        ds_id = ds["id"]
        print("数据集已创建: %s (id=%s)" % (DS_NAME, ds_id))

    # 2. Metrics 走 PUT（会吞单引号，第 3 步修正）；已存在的跳过（PUT 非幂等会 422）
    cur = api("/dataset/%s" % ds_id)
    existing = {mt["metric_name"] for mt in cur["result"].get("metrics", [])}
    missing = [m for m in METRICS if m[0] not in existing]
    if missing:
        api("/dataset/%s" % ds_id, "PUT", json={"metrics": [
            {"expression": m[2], "metric_name": m[0], "verbose_name": m[1],
             "description": m[1], "extra": "{}"} for m in missing]})
        print("metrics 已通过 API 写入: %s" % ", ".join(m[0] for m in missing))
    else:
        print("metrics 已存在，跳过 API 写入")

    # 3. 直写 sql_metrics 修正被吞的单引号（stdin 传脚本，避免引号转义地狱）
    fixes = [[m[0], m[3]] for m in METRICS]   # [[metric_name, 正确表达式]]
    script = (
        "import sqlite3, json\n"
        "conn = sqlite3.connect('/app/superset_home/superset.db')\n"
        "cur = conn.cursor()\n"
        "for name, expr in json.loads('''%s'''):\n"
        "    cur.execute('UPDATE sql_metrics SET expression=? WHERE table_id=? AND metric_name=?',\n"
        "               (expr, %d, name))\n"
        "conn.commit()\n"
        "conn.close()\n" % (json.dumps(fixes), ds_id))
    r = subprocess.run(
        ["docker", "exec", "-i", "superset", "python3", "-"],
        input=script, capture_output=True, text=True)
    if r.returncode != 0:
        print("sqlite 修正失败:", r.stderr[:300])
        sys.exit(1)
    print("sqlite 修正完成（引号已恢复）")

    # 4. 验证
    d = api("/dataset/%s" % ds_id)
    print("最终 Metrics:")
    for mt in d["result"]["metrics"]:
        print("  -", mt["verbose_name"], "|", mt["metric_name"], "|", mt["expression"])
    print("完成: http://localhost:8088/superset/dataset/%s/" % ds_id)


if __name__ == "__main__":
    main()
