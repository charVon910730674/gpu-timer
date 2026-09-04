"""Session 引擎：每小时从快照重放状态机（防抖），重建时段"""
import logging
from datetime import datetime

from . import config, db

log = logging.getLogger("sessions")


def _replay(snaps):
    """快照 [(ts, state, reason)] 升序 -> 时段段 [(state, start, end, ongoing, reason)]"""
    segments = []
    cur_stable = None
    seg_start = None
    seg_reason = None
    pending = None

    for ts, st, rs in snaps:
        if cur_stable is None:
            cur_stable, seg_start, seg_reason = st, ts, rs
            continue
        if st == cur_stable:
            seg_reason = rs
            pending = None
            continue
        # 状态变化
        if pending == st:
            # 确认翻转（连续 2 点）
            segments.append((cur_stable, seg_start, ts, False, seg_reason))
            cur_stable, seg_start, seg_reason = st, ts, rs
            pending = None
        else:
            pending = st

    if cur_stable is not None:
        last_ts = snaps[-1][0]
        # 尾部段：若最后快照状态即当前稳定态 → ongoing
        ongoing = (snaps[-1][1] == cur_stable)
        segments.append((cur_stable, seg_start, last_ts, ongoing, seg_reason))
    return segments


def rebuild_all():
    machines = db.get_machines()
    total = 0
    for mid, ip, psrc, enabled in machines:
        if not enabled:
            continue
        snaps = db.all_snapshots(mid)
        if len(snaps) < 1:
            continue
        segments = _replay(snaps)
        db.rebuild_sessions(mid, segments)
        total += len(segments)
    log.info("session 重建完成: %d 台, %d 段", len(machines), total)
    return total
