"""日报表导出：每台机器每日在线/故障/离线时长 CSV"""
import csv
import logging
from datetime import datetime, timedelta, date

from . import config, db

log = logging.getLogger("report")


def gen_daily(target_date=None):
    """生成某日（默认昨日）每台机器时长报表 -> /app/reports/daily_YYYY-MM-DD.csv"""
    if target_date is None:
        d = date.today() - timedelta(days=1)
    elif isinstance(target_date, str):
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        d = target_date
    start = datetime.combine(d, datetime.min.time())
    end = start + timedelta(days=1)

    rows = []
    for mid, ip, psrc, enabled in db.get_machines():
        if not enabled:
            continue
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state, COUNT(*)*5/60 FROM power_snapshots "
                    "WHERE machine_id=%s AND ts>=%s AND ts<%s GROUP BY state",
                    (mid, start, end))
                agg = dict(cur.fetchall())
        finally:
            conn.close()
        rows.append({
            "ip": ip, "date": str(d),
            "online_h": round(agg.get("online", 0), 2),
            "fault_h": round(agg.get("fault", 0), 2),
            "offline_h": round(agg.get("offline", 0), 2),
        })

    path = "/app/reports/daily_%s.csv" % d
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ip", "date", "online_h", "fault_h", "offline_h"])
        w.writeheader()
        w.writerows(rows)
    log.info("日报生成: %s (%d 台)", path, len(rows))
    return path


def gen_fault_detail(target_date=None):
    """导出故障/离线时段明细 CSV。默认昨日；传 'all' 导出全部历史。
    -> /app/reports/fault_detail_YYYY-MM-DD.csv
    """
    if target_date == "all":
        start, end = datetime(2026, 7, 1), datetime.now() + timedelta(days=1)
        suffix = "all"
    elif target_date is None:
        d = date.today() - timedelta(days=1)
        start = datetime.combine(d, datetime.min.time())
        end = start + timedelta(days=1)
        suffix = str(d)
    elif isinstance(target_date, str):
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
        start = datetime.combine(d, datetime.min.time())
        end = start + timedelta(days=1)
        suffix = str(d)
    else:
        d = target_date
        start = datetime.combine(d, datetime.min.time())
        end = start + timedelta(days=1)
        suffix = str(d)

    rows = []
    for mid, ip, psrc, enabled in db.get_machines():
        if not enabled:
            continue
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state, fault_reason, start_time, end_time, "
                    "duration_hours, ongoing FROM sessions "
                    "WHERE machine_id=%s AND state IN ('fault','offline') "
                    "AND start_time < %s AND end_time >= %s ORDER BY start_time",
                    (mid, end, start))
                for r in cur.fetchall():
                    rows.append({
                        "ip": ip, "state": r[0], "fault_reason": r[1],
                        "start_time": str(r[2]), "end_time": str(r[3]),
                        "hours": r[4], "ongoing": r[5],
                    })
        finally:
            conn.close()

    path = "/app/reports/fault_detail_%s.csv" % suffix
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ip", "state", "fault_reason",
                                          "start_time", "end_time", "hours", "ongoing"])
        w.writeheader()
        w.writerows(rows)
    log.info("故障明细导出: %s (%d 条)", path, len(rows))
    return path


def _target_range(target_date):
    """解析日期参数 -> (start, end, suffix)。None=昨日"""
    if target_date is None:
        d = date.today() - timedelta(days=1)
    elif isinstance(target_date, str):
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        d = target_date
    start = datetime.combine(d, datetime.min.time())
    return start, start + timedelta(days=1), str(d)


def gen_cpu_top20(target_date=None):
    """CPU 日均负载 TOP20 -> /app/reports/cpu_top20_YYYY-MM-DD.csv
    按 node_load1 日均值降序取 20；附每核负载（avg_load1 / 核数）便于跨机型比较
    """
    start, end, suffix = _target_range(target_date)
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT m.ip, "
                "  ROUND(AVG(u.cpu_load1), 3) AS avg_load1, "
                "  ROUND(AVG(u.cpu_load1) / NULLIF(AVG(u.cpu_cores), 0), 3) AS per_core, "
                "  MAX(u.cpu_load1) AS max_load1, COUNT(*) AS samples "
                "FROM util_samples u JOIN machines m ON m.id = u.machine_id "
                "WHERE u.ts >= %s AND u.ts < %s AND m.enabled = 1 "
                "  AND u.cpu_load1 IS NOT NULL "
                "GROUP BY m.ip ORDER BY avg_load1 DESC LIMIT 20",
                (start, end))
            rows = [{"ip": r[0], "date": suffix, "avg_load1": r[1],
                     "per_core_load": r[2], "max_load1": r[3], "samples": r[4]}
                    for r in cur.fetchall()]
    finally:
        conn.close()

    path = "/app/reports/cpu_top20_%s.csv" % suffix
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ip", "date", "avg_load1",
                                          "per_core_load", "max_load1", "samples"])
        w.writeheader()
        w.writerows(rows)
    log.info("CPU TOP20 生成: %s (%d 台)", path, len(rows))
    return path


def gen_gpu_top20(target_date=None):
    """GPU 日均利用率报表（全量机器，不限制 TOP20）-> /app/reports/full_gpu_YYYY-MM-DD.csv
    按全卡平均利用率日均值降序排列全部机器
    """
    start, end, suffix = _target_range(target_date)
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT m.ip, "
                "  ROUND(AVG(u.gpu_util_avg), 2) AS avg_util, "
                "  MAX(u.gpu_util_max) AS max_util, COUNT(*) AS samples "
                "FROM util_samples u JOIN machines m ON m.id = u.machine_id "
                "WHERE u.ts >= %s AND u.ts < %s AND m.enabled = 1 "
                "  AND u.gpu_util_avg IS NOT NULL "
                "GROUP BY m.ip ORDER BY avg_util DESC",
                (start, end))
            rows = [{"ip": r[0], "date": suffix, "avg_gpu_util": r[1],
                     "max_gpu_util": r[2], "samples": r[3]}
                    for r in cur.fetchall()]
    finally:
        conn.close()

    path = "/app/reports/full_gpu_%s.csv" % suffix
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ip", "date", "avg_gpu_util",
                                          "max_gpu_util", "samples"])
        w.writeheader()
        w.writerows(rows)
    log.info("GPU 利用率报表生成(全量): %s (%d 台)", path, len(rows))
    return path


def gen_gpu_temp_over85(target_date=None):
    """每日 GPU 高温统计（> 阈值，默认 85℃）-> /app/reports/gpu_temp_over85_YYYY-MM-DD.csv
    只列当日出现过任意卡超过阈值的机器：最热温度 / 最热卡编号 / 峰值时刻 / 超温时长
    """
    start, end, suffix = _target_range(target_date)
    thr = config.GPU_TEMP_OVER_THRESHOLD
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT m.ip, MAX(u.gpu_temp_max) AS max_temp, "
                "  ROUND(AVG(u.gpu_temp_max), 2) AS avg_max_temp, "
                "  SUM(u.gpu_temp_max > %s) AS over_samples, "
                "  COUNT(*) AS samples "
                "FROM util_samples u JOIN machines m ON m.id = u.machine_id "
                "WHERE u.ts >= %s AND u.ts < %s AND m.enabled = 1 "
                "  AND u.gpu_temp_max IS NOT NULL "
                "GROUP BY m.ip HAVING over_samples > 0 "
                "ORDER BY max_temp DESC", (thr, start, end))
            agg = cur.fetchall()

            rows = []
            for ip, max_temp, avg_max_temp, over_samples, samples in agg:
                # 峰值时刻的最热卡编号+序列号（温度倒序取第一条）
                cur.execute(
                    "SELECT u.gpu_temp_hot_idx, u.gpu_temp_hot_uuid, u.ts "
                    "FROM util_samples u "
                    "JOIN machines m ON m.id = u.machine_id "
                    "WHERE m.ip=%s AND u.ts >= %s AND u.ts < %s "
                    "  AND u.gpu_temp_max IS NOT NULL "
                    "ORDER BY u.gpu_temp_max DESC, u.ts ASC LIMIT 1",
                    (ip, start, end))
                r = cur.fetchone()
                rows.append({
                    "ip": ip, "date": suffix,
                    "threshold": thr,
                    "max_gpu_temp": max_temp,
                    "hot_gpu_idx": r[0] if r else "",
                    "hot_gpu_uuid": r[1] if r else "",
                    "peak_time": str(r[2]) if r else "",
                    "avg_max_temp": avg_max_temp,
                    "over_minutes": int(over_samples) * 5,
                    "over_samples": int(over_samples),
                    "samples": samples,
                })
    finally:
        conn.close()

    path = "/app/reports/gpu_temp_over85_%s.csv" % suffix
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ip", "date", "threshold",
                                          "max_gpu_temp", "hot_gpu_idx",
                                          "hot_gpu_uuid", "peak_time",
                                          "avg_max_temp", "over_minutes",
                                          "over_samples", "samples"])
        w.writeheader()
        w.writerows(rows)
    log.info("GPU 高温(>%s℃)统计生成: %s (%d 台)", thr, path, len(rows))
    return path


def gen_monthly(period=None):
    """生成月度汇总报表（在线总时长/故障/离线 + 在线率）"""
    if period is None:
        now = datetime.now()
        period = "%04d-%02d" % (now.year, now.month)
    y, m = int(period[:4]), int(period[5:7])
    start = datetime(y, m, 1)
    if m == 12:
        end = datetime(y + 1, 1, 1)
    else:
        end = datetime(y, m + 1, 1)

    rows = []
    for mid, ip, psrc, enabled in db.get_machines():
        if not enabled:
            continue
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state, COUNT(*) FROM power_snapshots "
                    "WHERE machine_id=%s AND ts>=%s AND ts<%s GROUP BY state",
                    (mid, start, end))
                agg = dict(cur.fetchall())
        finally:
            conn.close()
        total = sum(agg.values())
        online = agg.get("online", 0)
        rows.append({
            "ip": ip, "period": period,
            "online_h": round(online * 5 / 60, 2),
            "fault_h": round(agg.get("fault", 0) * 5 / 60, 2),
            "offline_h": round(agg.get("offline", 0) * 5 / 60, 2),
            "online_pct": round(online / total * 100, 2) if total else 0,
        })

    path = "/app/reports/monthly_%s.csv" % period
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ip", "period", "online_h", "fault_h", "offline_h", "online_pct"])
        w.writeheader()
        w.writerows(rows)
    log.info("月报生成: %s (%d 台)", path, len(rows))
    return path
