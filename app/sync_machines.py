"""机器同步：从 Prometheus 自动导入 GPU 节点到 machines 表"""
import logging

import requests

from . import config, db

log = logging.getLogger("sync")


def sync_machines():
    """导入 dcgm 覆盖的节点（Hostname 取自 DCGM label）"""
    url = config.PROM_URL + "/api/v1/query"
    try:
        r = requests.get(url, params={
            "query": 'count(DCGM_FI_DEV_GPU_UTIL) by (instance, Hostname)'},
            timeout=25)
        r.raise_for_status()
        res = r.json()["data"]["result"]
    except Exception as e:
        log.error("同步失败: %s", e)
        return 0

    seen = set()
    for x in res:
        m = x["metric"]
        ip = m.get("instance", "").split(":")[0]
        hostname = m.get("Hostname", "")
        if not ip or ip in seen:
            continue
        seen.add(ip)
        db.upsert_machine(ip, hostname)
    log.info("机器同步完成: %d 台 (dcgm)", len(seen))
    return len(seen)
