"""历史回填：从 Prometheus 保留期内数据重建快照（一次性工具）

用法: python -m app.fill_history [days]
"""
import sys
import re
import logging
from datetime import datetime, timedelta

import requests

from . import config, db
from .collector import judge

log = logging.getLogger("fill")


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


def build_sensor_index(results, patterns=None, excludes=(), types=None):
    """IPMI 传感器：{ip: {ts: 1}} 表示该时刻存在错误状态（state != 0）的匹配传感器
    patterns: name 正则列表；types: type 标签列表；两者任一命中即算匹配"""
    rxs = [re.compile(p) for p in (patterns or [])]
    idx = {}
    for x in results:
        name = x["metric"].get("name", "")
        if any(e in name for e in excludes):
            continue
        t = x["metric"].get("type", "")
        if not (any(rx.search(name) for rx in rxs) or (types and t in types)):
            continue
        ip = x["metric"].get("instance", "").split(":")[0]
        parts = ip.split(".")
        if len(parts) == 4 and parts[2] == "193":
            ip = "%s.%s.192.%s" % (parts[0], parts[1], parts[3])
        d = idx.setdefault(ip, {})
        for ts, v in x.get("values", []):
            fv = float(v)
            if fv == fv and fv != 0:    # NaN 跳过
                d[int(float(ts))] = 1
    return idx


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    end = datetime.now()
    start = end - timedelta(days=days)
    s_ts, e_ts = int(start.timestamp()), int(end.timestamp())
    # 对齐 5 分钟网格（与采集器一致，避免偏移网格产生重复/错位快照）
    s_ts -= s_ts % 300
    step = 300
    log.info("回填 %d 天: %s ~ %s", days, start, end)

    # 10 条件 range 查询
    power = build_index(range_query("ipmi_chassis_power_state", s_ts, e_ts, step))
    up = build_index(range_query('up{job="node_exporter"}', s_ts, e_ts, step))
    gpu = build_index(range_query("count(DCGM_FI_DEV_GPU_UTIL) by (instance)", s_ts, e_ts, step))
    uncorr = build_index(range_query("max(DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS) by (instance)", s_ts, e_ts, step))
    remap = build_index(range_query("max(DCGM_FI_DEV_ROW_REMAP_FAILURE) by (instance)", s_ts, e_ts, step))
    xid = build_index(range_query("count(DCGM_FI_DEV_XID_ERRORS) by (instance)", s_ts, e_ts, step))
    ibg = build_index(range_query("ib_global_status", s_ts, e_ts, step))
    ibp = build_index(range_query("min(node_infiniband_state_id) by (instance)", s_ts, e_ts, step))
    edac = build_index(range_query("max(increase(node_edac_uncorrectable_errors_total[1h])) by (instance)", s_ts, e_ts, step))
    edacc = build_index(range_query("max(increase(node_edac_correctable_errors_total[1h])) by (instance)", s_ts, e_ts, step))
    hwc = build_index(range_query("max(node_memory_HardwareCorrupted_bytes) by (instance)", s_ts, e_ts, step))
    disks = build_sensor_index(range_query("ipmi_sensor_state", s_ts, e_ts, step),
                               patterns=[r"NVME|HDD|SSD|DISK|RAID"], types=["Drive Slot"])
    cpus = build_sensor_index(range_query("ipmi_sensor_state", s_ts, e_ts, step),
                              patterns=[], types=["Processor"])
    ibcnt = build_index(range_query('count(node_infiniband_physical_state_id{device=~"mlx5_[0-9]+"} == 5) by (instance)', s_ts, e_ts, step))

    machines = db.get_machines()
    total_pts = 0
    for mid, ip, psrc, enabled in machines:
        if not enabled:
            continue
        # 该机器的时间轴：以 node up 数据为准
        up_d = up.get(ip, {})
        if not up_d:
            log.warning("机器 %s 无 up 历史，跳过", ip)
            continue
        power_d = power.get(ip, {})
        gpu_d = gpu.get(ip, {})
        uncorr_d = uncorr.get(ip, {})
        remap_d = remap.get(ip, {})
        xid_d = xid.get(ip, {})
        ibg_d = ibg.get(ip, {})
        ibp_d = ibp.get(ip, {})
        edac_d = edac.get(ip, {})
        edacc_d = edacc.get(ip, {})
        hwc_d = hwc.get(ip, {})
        disks_d = disks.get(ip, {})
        cpus_d = cpus.get(ip, {})
        ibcnt_d = ibcnt.get(ip, {})
        ts_list = sorted(up_d.keys())
        batch = []
        for ts in ts_list:
            # 各条件取该时间点最近值（容忍 300s 偏差）
            def near(idx, t):
                v = idx.get(t)
                if v is not None:
                    return v
                for dt in (150, -150, 450, -450):
                    v = idx.get(t + dt)
                    if v is not None:
                        return v
                return None

            c = {
                "ipmi": near(power_d, ts),
                "up": near(up_d, ts),
                "gpu_online": near(gpu_d, ts),
                "uncorr": near(uncorr_d, ts),
                "remap_fail": near(remap_d, ts),
                "xid": near(xid_d, ts),
                "ib_global": near(ibg_d, ts),
                "ib_port": near(ibp_d, ts),
                "edac_uncorr": near(edac_d, ts),
                "edac_corr_inc": near(edacc_d, ts),
                "hw_corrupted": near(hwc_d, ts),
                "disk_sensor": near(disks_d, ts),
                "cpu_sensor": near(cpus_d, ts),
                "ib_count": near(ibcnt_d, ts),
            }
            # 缺失指标处理（与实时采集一致：IB 缺失视为 OK）
            if c["ib_global"] is None:
                c["ib_global"] = config.IB_GLOBAL_OK
            if c["ib_port"] is None:
                c["ib_port"] = config.IB_STATE_ACTIVE
            if c["up"] is None:
                c["up"] = 0

            state, reason, po, mok, gon, gunc, xidv, ibok, ibpv, \
                memf, diskf, cpuf, iball = judge(c, psrc)
            batch.append((mid, datetime.fromtimestamp(ts), state, po, mok, gon,
                          gunc, xidv, ibok, ibpv, memf, diskf, cpuf, iball,
                          reason, psrc))
            if len(batch) >= 2000:
                _bulk(batch)
                total_pts += len(batch)
                batch = []
        if batch:
            _bulk(batch)
            total_pts += len(batch)
        log.info("机器 %s 回填完成", ip)
    log.info("回填完成: %d 台, %d 快照点", len(machines), total_pts)


def _bulk(rows):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT IGNORE INTO power_snapshots "
                "(machine_id, ts, state, power_on, machine_ok, gpu_online, "
                " gpu_uncorrectable, xid_error, ib_link_ok, ib_port_ok, "
                " mem_fault, disk_fault, cpu_fault, ib_all_ok, "
                " fault_reason, src) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
