"""数据库访问层（pymysql，短连接）"""
import pymysql
from . import config


def connect():
    return pymysql.connect(
        host=config.MYSQL["host"],
        port=config.MYSQL["port"],
        user=config.MYSQL["user"],
        password=config.MYSQL["password"],
        database=config.MYSQL["db"],
        charset=config.MYSQL["charset"],
        autocommit=True,
        connect_timeout=10,
    )


def get_machines():
    """返回 [(id, ip, power_source, enabled)]"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ip, power_source, enabled FROM machines ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()


def upsert_machine(ip, hostname, power_source="ipmi", spec="8xH100"):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO machines (ip, hostname, power_source, spec) "
                "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE hostname=VALUES(hostname)",
                (ip, hostname, power_source, spec))
    finally:
        conn.close()


def last_snapshots(machine_id, n=2):
    """最近 n 条快照 state，按 ts 倒序"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM power_snapshots WHERE machine_id=%s "
                "ORDER BY ts DESC LIMIT %s", (machine_id, n))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def write_snapshot(mid, ts, state, power_on, machine_ok, gpu_online,
                   gpu_uncorr, xid, ib_link_ok, ib_port_ok,
                   mem_fault, disk_fault, cpu_fault, ib_all_ok, reason, src):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO power_snapshots "
                "(machine_id, ts, state, power_on, machine_ok, gpu_online, "
                " gpu_uncorrectable, xid_error, ib_link_ok, ib_port_ok, "
                " mem_fault, disk_fault, cpu_fault, ib_all_ok, "
                " fault_reason, src) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (mid, ts, state, power_on, machine_ok, gpu_online,
                 gpu_uncorr, xid, ib_link_ok, ib_port_ok,
                 mem_fault, disk_fault, cpu_fault, ib_all_ok, reason, src))
    finally:
        conn.close()


def write_util_sample(mid, ts, cpu_load1, cpu_cores, gpu_util_avg, gpu_util_max,
                      gpu_temp_avg=None, gpu_temp_max=None,
                      gpu_temp_hot_idx=None, gpu_temp_hot_uuid=None):
    """写入负载/利用率采样点（缺失字段存 NULL）"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO util_samples "
                "(machine_id, ts, cpu_load1, cpu_cores, gpu_util_avg, gpu_util_max, "
                " gpu_temp_avg, gpu_temp_max, gpu_temp_hot_idx, gpu_temp_hot_uuid) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (mid, ts, cpu_load1, cpu_cores, gpu_util_avg, gpu_util_max,
                 gpu_temp_avg, gpu_temp_max, gpu_temp_hot_idx, gpu_temp_hot_uuid))
    finally:
        conn.close()


def write_event(mid, event_type, ts, reason, src):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO power_events "
                "(machine_id, event_type, fault_reason, ts, src) "
                "VALUES (%s,%s,%s,%s,%s)",
                (mid, event_type, reason, ts, src))
    finally:
        conn.close()


def all_snapshots(machine_id):
    """该机器全部快照 (ts, state, fault_reason) 升序"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts, state, fault_reason FROM power_snapshots WHERE machine_id=%s "
                "ORDER BY ts ASC", (machine_id,))
            return cur.fetchall()
    finally:
        conn.close()


def rebuild_sessions(machine_id, segments):
    """事务重建 sessions。segments: [(state, start, end, ongoing, reason)]"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE machine_id=%s", (machine_id,))
            for state, start, end, ongoing, reason in segments:
                hours = round((end - start).total_seconds() / 3600.0, 4)
                if hours <= 0 and not ongoing:
                    continue
                cur.execute(
                    "INSERT INTO sessions "
                    "(machine_id, state, start_time, end_time, duration_hours, ongoing, fault_reason) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (machine_id, state, start, end, hours, 1 if ongoing else 0, reason))
    finally:
        conn.close()
