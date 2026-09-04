"""GPU 在线计时系统 v7 - 主入口（APScheduler）"""
import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from . import collector, sessions, sync_machines, report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def job_collect():
    collector.collect_once()


def job_sessions():
    sessions.rebuild_all()


def job_sync():
    sync_machines.sync_machines()


def main():
    log.info("GPU 计时系统启动")

    # 启动即同步机器 + 立即采集一轮
    n = sync_machines.sync_machines()
    log.info("初始机器数: %d", n)
    try:
        collector.collect_once()
    except Exception as e:
        log.error("初始采集失败: %s", e)

    sched = BlockingScheduler(timezone="Asia/Shanghai")
    # 每 5 分钟采集（注意：不能传 next_run_time=None，那会把 job 挂起为 paused 永不触发）
    sched.add_job(job_collect, IntervalTrigger(minutes=5, jitter=10),
                  id="collect")
    # 每小时重建 session
    sched.add_job(job_sessions, IntervalTrigger(hours=1, jitter=30),
                  id="sessions")
    # 每 6 小时同步机器
    sched.add_job(job_sync, IntervalTrigger(hours=6, jitter=60),
                  id="sync")
    # 每日 01:00 日报
    sched.add_job(lambda: report.gen_daily(), CronTrigger(hour=1, minute=0),
                  id="report_daily")
    # 每日 01:05 故障/离线明细
    sched.add_job(lambda: report.gen_fault_detail(), CronTrigger(hour=1, minute=5),
                  id="report_fault_detail")
    # 每日 01:10 CPU 日均负载 TOP20 / 01:12 GPU 日均利用率 TOP20
    sched.add_job(lambda: report.gen_cpu_top20(), CronTrigger(hour=1, minute=10),
                  id="report_cpu_top20")
    sched.add_job(lambda: report.gen_gpu_top20(), CronTrigger(hour=1, minute=12),
                  id="report_gpu_top20")
    # 每日 01:14 GPU 高温(>85℃)统计
    sched.add_job(lambda: report.gen_gpu_temp_over85(), CronTrigger(hour=1, minute=14),
                  id="report_gpu_temp_over85")
    # 每月 1 日 02:00 月报
    sched.add_job(lambda: report.gen_monthly(), CronTrigger(day=1, hour=2, minute=0),
                  id="report_monthly")
    sched.start()


if __name__ == "__main__":
    main()
