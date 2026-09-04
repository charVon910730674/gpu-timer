"""util_samples 历史回填：从 Prometheus 保留期内重建负载/利用率/GPU 温度采样（一次性工具）

用法: python -m app.fill_util [days]
依赖 util_samples 表已建（sql/schema.sql，含 gpu_temp_* 列）
"""
import sys
import logging
from datetime import datetime, timedelta

import requests

from . import config, db

log = logging.getLogger("fill_util")


def range_query(promql, start, end, step=300):
    r = requests.get(config.PROM_URL + "/api/v1/query_range",
                     params={"query": promql, "start": start, "end": end,
                             "step": step}, timeout=120)
    r.raise_for_status()
    return r.json()["data"]["result"]


def build_index(results):
    """{ip: {ts: value}}"""
    idx = {}
    for x in results:
        ip = x["metric"].get("instance", "").split(":")[0]
        d = idx.setdefault(ip, {})
        for ts, v in x.get("values", []):
            d[int(float(ts))] = float(v)
    return idx


def instant_query(promql):
    """即时查询（核数等不变值用一次查询即可，避免 range 大 series 超限）"""
    r = requests.get(config.PROM_URL + "/api/v1/query",
                     params={"query": promql}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["result"]


def build_instant_index(results):
    """{ip: float} 即时值"""
    idx = {}
    for x in results:
        ip = x["metric"].get("instance", "").split(":")[0]
        idx[ip] = float(x["value"][1])
    return idx


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    end = datetime.now()
    start = end - timedelta(days=days)
    s_ts, e_ts = int(start.timestamp()), int(end.timestamp())
    # 对齐到 5 分钟网格（epoch % 300 == 0 即本地 5 分钟边界，因东八区偏移 8h 恰为 300 整数倍）
    # 保证与采集器 ts 同一网格，重跑幂等（ON DUPLICATE KEY UPDATE 只更新不新增）
    s_ts -= s_ts % 300
    step = 300
    log.info("回填 %d 天 util 采样: %s ~ %s", days, start, end)

    load1 = build_index(range_query("node_load1", s_ts, e_ts, step))
    # 核数：即时查询一次（核数不变；range count by 会因 series 过多 422/超时）
    cores = build_instant_index(instant_query(
        'count(node_cpu_seconds_total{mode="idle"}) by (instance)'))
    util_avg = build_index(range_query(
        "avg(DCGM_FI_DEV_GPU_UTIL) by (instance)", s_ts, e_ts, step))
    util_max = build_index(range_query(
        "max(DCGM_FI_DEV_GPU_UTIL) by (instance)", s_ts, e_ts, step))
    temp_avg = build_index(range_query(
        "avg(DCGM_FI_DEV_GPU_TEMP) by (instance)", s_ts, e_ts, step))
    temp_max = build_index(range_query(
        "max(DCGM_FI_DEV_GPU_TEMP) by (instance)", s_ts, e_ts, step))

    machines = db.get_machines()
    total = 0
    for mid, ip, psrc, enabled in machines:
        if not enabled:
            continue
        ld = load1.get(ip, {})
        if not ld:
            log.warning("机器 %s 无 node_load1 历史，跳过", ip)
            continue
        cval = cores.get(ip)
        ua = util_avg.get(ip, {})
        um = util_max.get(ip, {})
        ta = temp_avg.get(ip, {})
        tm = temp_max.get(ip, {})
        # 最热卡编号+序列号：逐机小查询（8 卡/机；全量原始序列 range 会 series 过多超限）
        th = {}
        if tm:
            try:
                pat = ip.replace(".", r"\.")
                # 注意：正则里的 \. 必须用反引号原始字符串，双引号 PromQL 字符串会把 \. 当非法转义报 400
                for x in range_query(
                        'DCGM_FI_DEV_GPU_TEMP{instance=~`^%s:.*`}' % pat,
                        s_ts, e_ts, step):
                    gpu = x["metric"].get("gpu", "")
                    uuid = x["metric"].get("UUID", "")
                    for ts, v in x.get("values", []):
                        th.setdefault(int(float(ts)), {})[gpu] = (float(v), uuid)
                # 每点 argmax：保留 (卡号, uuid) 元组
                th2 = {}
                for ts, gpus in th.items():
                    gpu, (v, uuid) = max(gpus.items(), key=lambda kv: kv[1][0])
                    th2[ts] = (gpu, uuid)
                th = th2
            except Exception as e:
                log.warning("机器 %s 最热卡回填失败（忽略）: %s", ip, e)
        batch = []
        for ts in sorted(ld.keys()):
            def near(idx, t):
                v = idx.get(t)
                if v is not None:
                    return v
                for dt in (150, -150, 450, -450):
                    v = idx.get(t + dt)
                    if v is not None:
                        return v
                return None

            hot = near(th, ts)
            hot_idx, hot_uuid = hot if hot else (None, None)
            batch.append((mid, datetime.fromtimestamp(ts),
                          near(ld, ts), cval,
                          near(ua, ts), near(um, ts),
                          near(ta, ts), near(tm, ts),
                          hot_idx, hot_uuid))
            if len(batch) >= 2000:
                total += _bulk(batch)
                batch = []
        if batch:
            total += _bulk(batch)
        log.info("机器 %s 回填完成", ip)
    log.info("util 回填完成: %d 台, %d 采样点", len(machines), total)


def _bulk(rows):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO util_samples "
                "(machine_id, ts, cpu_load1, cpu_cores, gpu_util_avg, gpu_util_max, "
                " gpu_temp_avg, gpu_temp_max, gpu_temp_hot_idx, gpu_temp_hot_uuid) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE "
                "gpu_temp_avg=VALUES(gpu_temp_avg), "
                "gpu_temp_max=VALUES(gpu_temp_max), "
                "gpu_temp_hot_idx=VALUES(gpu_temp_hot_idx), "
                "gpu_temp_hot_uuid=VALUES(gpu_temp_hot_uuid)", rows)
        return len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
