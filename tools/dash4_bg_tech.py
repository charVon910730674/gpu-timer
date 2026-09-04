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
print("auth:", "OK" if tok and csrf else "FAIL")

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

# dash3 的 css（科技风）
d3 = req("GET", "/dashboard/3", tok=tok).get("result", {})
css3 = d3.get("css") or ""
print("dash3 css len:", len(css3))

# dash4 其他字段保持不变，只换 css
d4 = req("GET", "/dashboard/4", tok=tok).get("result", {})
r = write("PUT", "/dashboard/4", {
    "css": css3,
    "position_json": d4.get("position_json"),
    "json_metadata": d4.get("json_metadata"),
    "dashboard_title": d4.get("dashboard_title"),
    "published": True,
})
print("dash4 css 更新:", "OK" if "ERROR" not in r else r)

# 验证
d4v = req("GET", "/dashboard/4", tok=tok).get("result", {})
print("验证 dash4 css len:", len(d4v.get("css") or ""),
      "| 与 dash3 一致:", d4v.get("css") == css3)
