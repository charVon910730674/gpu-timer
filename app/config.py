"""GPU 服务器在线计时系统 v7 - 配置"""
import os

MYSQL = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    # 仓库公开版：密码不留默认值，必须经环境变量 MYSQL_PASSWORD 注入（内部 workspace 版保留默认）
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "db": os.environ.get("MYSQL_DB", "gpu_timer"),
    "charset": "utf8mb4",
}

PROM_URL = os.environ.get("PROM_URL", "http://127.0.0.1:9090")

# 在线判定阈值
GPU_ACTIVE_THRESHOLD = 5          # 保留：v7 判定不含利用率阈值（电源/健康判定）
IB_STATE_ACTIVE = 4               # node_infiniband_state_id active
IB_GLOBAL_OK = 1                  # ib_global_status ok
MEM_EDAC_CORR_THRESHOLD = 10      # 1h 可纠正内存错误阈值（与 node-exporter 组 Memory_hardware 告警一致）
GPU_TEMP_OVER_THRESHOLD = float(os.environ.get("GPU_TEMP_OVER_THRESHOLD", "85"))  # 每日 GPU 高温报表阈值 ℃

# 采样与防抖
SAMPLE_MINUTES = 5                # 采样周期
DEBOUNCE_POINTS = 2               # 连续 2 点确认翻转（10 分钟防抖）
