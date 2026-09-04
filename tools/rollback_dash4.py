import json, os, sys, urllib.request, http.cookiejar

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUPERSET_BASE", "http://127.0.0.1:8088")).rstrip("/") + "/api/v1"
USER = os.environ.get("SUPERSET_USER", "admin")
PWD = os.environ.get("SUPERSET_PWD", "")
if not PWD:
    sys.exit("请通过环境变量提供凭据: SUPERSET_PWD（可选 SUPERSET_BASE / SUPERSET_USER）")
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def req(method, path, data=None, tok=None):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if tok:
        r.add_header("Authorization", "Bearer " + tok)
    body = json.dumps(data).encode() if data is not None else None
    try:
        with opener.open(r, body, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ERROR": str(e)}

tok = req("POST", "/security/login",
          {"username": USER, "password": PWD,
           "provider": "db", "refresh": True}).get("access_token", "")
csrf = req("GET", "/security/csrf_token/", tok=tok).get("result", "")
print("auth:", "OK" if tok and csrf else "FAIL", "csrf:", csrf[:10], "...")

def write(method, path, data):
    r = urllib.request.Request(BASE + path, data=json.dumps(data).encode(), method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", "Bearer " + tok)
    r.add_header("X-CSRFToken", csrf)
    try:
        with opener.open(r, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ERROR": str(e)}

# 1. dash4 CSS 清空（回退到 08-12 改版前）
d4 = req("GET", "/dashboard/4", tok=tok).get("result", {})
r = write("PUT", "/dashboard/4", {
    "css": "",
    "position_json": d4.get("position_json"),
    "json_metadata": d4.get("json_metadata"),
    "dashboard_title": d4.get("dashboard_title"),
    "published": True,
})
print("dash4 css ->", "OK" if "ERROR" not in r else r)

# 2. 28 个图表 metric label 还原 + hasCustomLabel 关闭
CH = [3,4,12,16,17,18,19,20,21,22,23,24,25,26,
      30,31,32,33,34,35,36,38,39,40,41,42,44,45]
SUM_CH = {45}
ok, skip = [], []
for cid in CH:
    c = req("GET", "/chart/%d" % cid, tok=tok).get("result", {})
    params = c.get("params") or {}
    if isinstance(params, str):
        params = json.loads(params)
    auto = "SUM(value)" if cid in SUM_CH else "MAX(value)"
    changed = False
    for m in params.get("metrics") or []:
        if isinstance(m, dict) and m.get("hasCustomLabel"):
            m["label"] = auto
            m["hasCustomLabel"] = False
            changed = True
    if params.get("metric") and isinstance(params["metric"], dict) \
            and params["metric"].get("hasCustomLabel"):
        params["metric"]["label"] = auto
        params["metric"]["hasCustomLabel"] = False
        changed = True
    if not changed:
        skip.append(cid)
        continue
    r = write("PUT", "/chart/%d" % cid, {"params": json.dumps(params)})
    (ok if "ERROR" not in r else skip).append(cid)
print("已还原 label 的图表:", sorted(ok))
print("跳过(无需改):", sorted(skip))

# 3. 验证
d4v = req("GET", "/dashboard/4", tok=tok).get("result", {})
print("验证 dash4 css len:", len(d4v.get("css") or ""))
for cid in [3, 30, 45, 19]:
    cv = req("GET", "/chart/%d" % cid, tok=tok).get("result", {})
    pv = cv.get("params") or {}
    if isinstance(pv, str):
        pv = json.loads(pv)
    ms = pv.get("metrics") or ([pv["metric"]] if pv.get("metric") else [])
    print("  chart", cid, "->", [(m.get("label"), m.get("hasCustomLabel")) for m in ms if isinstance(m, dict)])
