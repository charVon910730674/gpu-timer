"""在线状态采集器：每 5 分钟 10 条件判定，写快照（防抖确认后写事件）"""
import logging
import re
from datetime import datetime, timedelta

import requests

from . import config, db

log = logging.getLogger("collector")

# 防抖 pending 状态（内存，重启丢失可接受）
_pending = {}


def query(promql):
    r = requests.get(config.PROM_URL + "/api/v1/query",
                     params={"query": promql}, timeout=25)
    r.raise_for_status()
    return r.json()["data"]["result"]


def _collect_conditions():
    """批量查询 10 条件，返回 {ip: {...}}"""
    results = {}

    def put(metric, key, transform=None):
        for x in metric:
            ip = x["metric"].get("instance", "").split(":")[0]
            v = float(x["value"][1])
            results.setdefault(ip, {})[key] = transform(v) if transform else int(v)

    # 1. 机器正常（node 探活）
    put(query('up{job="node_exporter"}'), "up")
    # 2. IPMI 电源（193.x BMC -> 192.x 节点）
    for x in query("ipmi_chassis_power_state"):
        bmc = x["metric"].get("instance", "").split(":")[0]
        parts = bmc.split(".")
        if len(parts) == 4 and parts[2] == "193":
            ip = "%s.%s.192.%s" % (parts[0], parts[1], parts[3])
            results.setdefault(ip, {})["ipmi"] = int(float(x["value"][1]))
    # 3. GPU 在线
    put(query("count(DCGM_FI_DEV_GPU_UTIL) by (instance)"), "gpu_online",
        lambda v: 1 if v > 0 else 0)
    # 4. 不可纠正错误 / 重映射失败
    put(query("max(DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS) by (instance)"), "uncorr")
    put(query("max(DCGM_FI_DEV_ROW_REMAP_FAILURE) by (instance)"), "remap_fail")
    # 5. XID 错误（事件型：有序列即有错）
    put(query("count(DCGM_FI_DEV_XID_ERRORS) by (instance)"), "xid")
    # 6. IB 全局状态
    put(query("ib_global_status"), "ib_global")
    # 7. IB 端口状态（全部端口需 active）
    put(query("min(node_infiniband_state_id) by (instance)"), "ib_port")
    # 8. 内存硬件故障（node_exporter，与告警规则同口径）
    #    increase(node_edac_correctable_errors_total[1h]) > 10
    #    or increase(node_edac_uncorrectable_errors_total[1h]) > 0
    #    or node_memory_HardwareCorrupted_bytes > 0
    put(query("max(increase(node_edac_uncorrectable_errors_total[1h])) by (instance)"),
        "edac_uncorr", lambda v: v)
    put(query("max(increase(node_edac_correctable_errors_total[1h])) by (instance)"),
        "edac_corr_inc", lambda v: v)
    put(query("max(node_memory_HardwareCorrupted_bytes) by (instance)"), "hw_corrupted")
    # 9. IPMI 硬件传感器错误状态 != 0（193.x BMC -> 192.x 节点）
    #    磁盘: type=Drive Slot 或 NVME/HDD/SSD/DISK/RAID | CPU: type=Processor
    for x in query("ipmi_sensor_state"):
        bmc = x["metric"].get("instance", "").split(":")[0]
        parts = bmc.split(".")
        if len(parts) == 4 and parts[2] == "193":
            ip = "%s.%s.192.%s" % (parts[0], parts[1], parts[3])
            name = x["metric"].get("name", "")
            stype = x["metric"].get("type", "")
            v = float(x["value"][1])
            if v != v:          # NaN（BMC 无读数）跳过
                continue
            st = int(v)
            if st == 0:
                continue
            d = results.setdefault(ip, {})
            if stype == "Drive Slot" or re.search(r"NVME|HDD|SSD|DISK|RAID", name):
                d["disk_sensor"] = 1
            elif stype == "Processor":
                d["cpu_sensor"] = 1
    # 10. IB 卡数量（8 张 mlx5_N 在线；整机离线/无 IB 采集 = 无序列，judge 视为 OK）
    put(query('count(node_infiniband_physical_state_id{device=~"mlx5_[0-9]+"} == 5) by (instance)'), "ib_count")
    # 11. CPU 1 分钟平均负载（node_exporter）
    put(query("node_load1"), "cpu_load1", lambda v: v)
    # 12. CPU 逻辑核数（node_cpu_seconds_total 每核一条 idle）
    put(query('count(node_cpu_seconds_total{mode="idle"}) by (instance)'), "cpu_cores")
    # 13. GPU 利用率：全卡平均 / 最大（DCGM 0-100）
    put(query("avg(DCGM_FI_DEV_GPU_UTIL) by (instance)"), "gpu_util_avg", lambda v: v)
    put(query("max(DCGM_FI_DEV_GPU_UTIL) by (instance)"), "gpu_util_max", lambda v: v)
    # 14. GPU 温度（DCGM，℃）：全卡平均 / 最热卡 / 最热卡编号+序列号（dcgm label gpu/UUID）
    put(query("avg(DCGM_FI_DEV_GPU_TEMP) by (instance)"), "gpu_temp_avg", lambda v: v)
    put(query("max(DCGM_FI_DEV_GPU_TEMP) by (instance)"), "gpu_temp_max", lambda v: v)
    for x in query("DCGM_FI_DEV_GPU_TEMP"):
        ip = x["metric"].get("instance", "").split(":")[0]
        v = float(x["value"][1])
        d = results.setdefault(ip, {})
        m = d.get("gpu_temp_max")
        if m is not None and v >= m and "gpu_temp_hot_idx" not in d:
            d["gpu_temp_hot_idx"] = x["metric"].get("gpu", "")
            d["gpu_temp_hot_uuid"] = x["metric"].get("UUID", "")
    return results


def judge(c, power_source):
    """单台机器 10 条件判定 -> (state, reason, 各条件值)"""
    up = c.get("up") or 0
    ipmi = c.get("ipmi")          # None = 无 IPMI 数据
    power_on = ipmi if ipmi is not None else up   # IPMI 优先，无则探活兜底
    machine_ok = up
    gpu_online = 1 if (c.get("gpu_online") or 0) > 0 else 0
    uncorr = c.get("uncorr") or 0
    remap_fail = c.get("remap_fail") or 0
    xid = c.get("xid") or 0
    ib_global = c.get("ib_global", config.IB_GLOBAL_OK)   # 缺失视为 OK（设计）
    ib_port = c.get("ib_port", config.IB_STATE_ACTIVE)    # 缺失视为 OK（设计）

    gpu_uncorr = 1 if (uncorr > 0 or remap_fail > 0) else 0
    no_xid = 1 if xid == 0 else 0
    ib_link_ok = 1 if ib_global == config.IB_GLOBAL_OK else 0
    ib_port_ok = 1 if ib_port == config.IB_STATE_ACTIVE else 0
    # 硬件故障：内存 = EDAC 1h 增长超阈值 或 HardwareCorrupted 页 > 0
    edac_uncorr = c.get("edac_uncorr") or 0
    edac_corr_inc = c.get("edac_corr_inc") or 0
    hw_corrupted = c.get("hw_corrupted") or 0
    mem_fault = 1 if (edac_uncorr > 0
                      or edac_corr_inc > config.MEM_EDAC_CORR_THRESHOLD
                      or hw_corrupted > 0) else 0
    disk_fault = 1 if c.get("disk_sensor") == 1 else 0
    cpu_fault = 1 if c.get("cpu_sensor") == 1 else 0
    ib_count = c.get("ib_count")          # None = 无 IB 采集（整机离线等）视为 OK
    ib_all_ok = 1 if (ib_count is None or ib_count >= 8) else 0

    faults = []
    if not machine_ok:
        faults.append("machine_down")
    if not gpu_online:
        faults.append("gpu_down")
    if gpu_uncorr:
        faults.append("gpu_uncorrectable")
    if not no_xid:
        faults.append("xid")
    if not ib_link_ok:
        faults.append("ib_link_down")
    if not ib_port_ok:
        faults.append("ib_port_down")
    if mem_fault:
        faults.append("mem_fault")
    if disk_fault:
        faults.append("disk_fault")
    if cpu_fault:
        faults.append("cpu_fault")
    if not ib_all_ok:
        faults.append("ib_card_missing")

    if not power_on:
        state, reason = "offline", None
    elif faults:
        state, reason = "fault", "+".join(faults)
    else:
        state, reason = "online", None

    return (state, reason, power_on, machine_ok, gpu_online,
            gpu_uncorr, xid, ib_link_ok, ib_port_ok,
            mem_fault, disk_fault, cpu_fault, ib_all_ok)


def collect_once():
    """执行一轮采集。返回处理的机器数"""
    now = datetime.now()
    ts = (now - timedelta(minutes=now.minute % config.SAMPLE_MINUTES,
                          seconds=now.second, microseconds=now.microsecond))

    try:
        conds = _collect_conditions()
    except Exception as e:
        log.error("Prometheus 查询失败: %s", e)
        return 0

    machines = db.get_machines()
    n = 0
    for mid, ip, psrc, enabled in machines:
        if not enabled:
            continue
        c = conds.get(ip, {})
        state, reason, po, mok, gon, gunc, xid, ibok, ibp, \
            memf, diskf, cpuf, iball = judge(c, psrc)
        db.write_snapshot(mid, ts, state, po, mok, gon, gunc, xid, ibok, ibp,
                          memf, diskf, cpuf, iball, reason, psrc)

        # 负载/利用率采样（缺失字段存 NULL，不影响主流程）
        db.write_util_sample(mid, ts, c.get("cpu_load1"), c.get("cpu_cores"),
                             c.get("gpu_util_avg"), c.get("gpu_util_max"),
                             c.get("gpu_temp_avg"), c.get("gpu_temp_max"),
                             c.get("gpu_temp_hot_idx"), c.get("gpu_temp_hot_uuid"))

        # 防抖事件：新状态连续 2 点确认
        prev = db.last_snapshots(mid, 1)
        prev_state = prev[0] if prev else None
        if state != prev_state:
            if _pending.get(mid) == state:
                db.write_event(mid, state, ts, reason, psrc)
                _pending.pop(mid, None)
            else:
                _pending[mid] = state
        else:
            _pending.pop(mid, None)
        n += 1
    log.info("采集完成: %d 台, ts=%s", n, ts)
    return n
