#!/usr/bin/env python3
"""导出 Prometheus 某时间窗口内的全部数据（HTTP API 方式，无需 admin API）

原理（与 promdump 相同）：
  1. GET /api/v1/label/__name__/values 拿到全部指标名
  2. 对每个指标调 /api/v1/query_range，按 --chunk-min 分块查询（避免单次响应过大）
  3. 逐指标写入 JSONL（每行: {"metric": 名称, "series": [...]}）

用法:
  python3 prom_export.py <base_url> <hours> [--step 15] [--out prom_export.jsonl]
  python3 prom_export.py http://127.0.0.1:9090 5 --out /root/prom_5h.jsonl
  python3 prom_export.py http://127.0.0.1:9090 5 --match "DCGM|node_load"   # 只导匹配的
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request


def api_get(url, params, timeout=120):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(url + "?" + q, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="Prometheus 地址，如 http://127.0.0.1:9090")
    ap.add_argument("hours", type=float, help="导出最近多少小时")
    ap.add_argument("--step", type=int, default=15, help="采样步长(秒)，默认 15")
    ap.add_argument("--out", default="prom_export.jsonl", help="输出文件")
    ap.add_argument("--match", default=None, help="只导出指标名匹配该正则的")
    ap.add_argument("--chunk-min", type=int, default=60, help="时间分块(分钟)，默认 60")
    args = ap.parse_args()

    end = time.time()
    start = end - args.hours * 3600

    names = api_get(args.base + "/api/v1/label/__name__/values", {})["data"]
    if args.match:
        rx = re.compile(args.match)
        names = [n for n in names if rx.search(n)]
    print("指标数: %d, 窗口: %.1fh, step=%ds, 输出: %s"
          % (len(names), args.hours, args.step, args.out), file=sys.stderr)

    chunk = args.chunk_min * 60
    ok = fail = 0
    t0 = time.time()
    with open(args.out, "w") as f:
        for i, name in enumerate(names, 1):
            series_all, err = [], None
            for cs in range(int(start), int(end), chunk):
                ce = min(cs + chunk, int(end))
                try:
                    d = api_get(args.base + "/api/v1/query_range",
                                {"query": name, "start": cs, "end": ce, "step": args.step})
                    series_all.extend(d["data"]["result"])
                except Exception as e:
                    err = str(e)
                    break
            if err:
                fail += 1
                print("[%d/%d] FAIL %s: %s" % (i, len(names), name, err), file=sys.stderr)
                continue
            f.write(json.dumps({"metric": name, "series": series_all},
                               ensure_ascii=False) + "\n")
            ok += 1
            if i % 100 == 0:
                print("进度 %d/%d (%.0fs)" % (i, len(names), time.time() - t0),
                      file=sys.stderr)
    print("完成: 成功 %d, 失败 %d -> %s" % (ok, fail, args.out), file=sys.stderr)


if __name__ == "__main__":
    main()
