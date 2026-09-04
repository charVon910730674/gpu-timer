# gpu-timer — GPU 服务器在线计时系统

两江 HPC 集群 **8×H100 GPU 节点在线计时系统**：从 Prometheus 采集 IPMI/node/DCGM/IB 指标，按 10 条件判定每台机器 online/fault/offline 三态，5 分钟采样落 MySQL，输出 Superset 看板、Prometheus 告警与每日 CSV 报表（时长/故障/负载 TOP20/GPU 高温）。**在线即计时**（在线时长 = 使用时长，按台计费扩展）。

> 完整开发历程（需求 6 轮演进、采集停摆事故、fault 检测内迁、两次数据修复、踩坑 30+ 条，2026-08-11 ~ 08-27）见 [docs/开发记录.md](docs/开发记录.md)。
> 原始设计文档见 [docs/设计文档-在线计时系统-v7.md](docs/设计文档-在线计时系统-v7.md)。
>
> 🔒 **脱敏说明**：文中示例 IP 为 RFC 5737 文档保留段（末位保留以对应机器编号，如 250/66 号），口令均为占位符（`<DB_PWD>` 等），真实值仅存于内部环境。

---

## 🏗️ 架构

```
Prometheus(IPMI+node+DCGM+IB, 250) ─▶ gpu-timer (Python + APScheduler)
                                    ├─ 5min 采集器（10 条件判定 + 防抖）
                                    │   └─ 顺带采集负载/利用率/GPU 温度 → util_samples
                                    ├─ 1h session 重建（幂等）
                                    ├─ 6h 机器同步（dcgm 自动发现）
                                    ├─ 每日 01:00 日报 + 01:05 故障明细
                                    ├─ 每日 01:10 CPU TOP20 + 01:12 GPU 全量 + 01:14 高温(>85℃)
                                    └─ 每月 1 日 02:00 月报
                                        │
                                        ▼
                              MySQL(gpu_timer 库)
              machines / power_snapshots / power_events / sessions / util_samples
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
        Superset dashboard 5「GPU 服务器在线计时」   Prometheus 告警 → alertmanager → 钉钉
        （9 图表：状态/趋势/排行/故障/TOP20/高温）   （dcgm/IB/硬件故障规则，HUP 热重载）
```

- 部署：`gpu-timer:1.2` 容器（`--network=host --restart=unless-stopped`），代码挂载 `/opt/gpu-timer/app`，250 宿主机（203.0.113.250）
- 构建链路：142（有外网）构建镜像 → `docker save|gzip` 管道 → 250 `docker load`

## 🧩 目录结构

```
gpu-timer/
├── README.md                  ← 本文档
├── Dockerfile                 ← 容器镜像（python:3.11-slim，清华源）
├── requirements.txt           ← pymysql / requests / apscheduler
├── superset_config.py         ← 250 superset-fc 配置（pymysql 方言注册等）
├── app/                       ← 核心代码（当前线上版：10 条件 + util_samples + 温度）
│   ├── main.py                ← APScheduler 调度入口（5min/1h/6h + 每日 5 报表 + 月报）
│   ├── collector.py           ← 采集器：10 条件判定 + 负载/温度顺带采集
│   ├── config.py              ← 配置（MySQL/Prometheus/阈值，环境变量可覆盖）
│   ├── db.py                  ← 快照/事件/时段/负载采样写入
│   ├── sessions.py            ← session 重放重建（幂等）
│   ├── sync_machines.py       ← 机器自动同步（Prometheus dcgm 发现）
│   ├── fill_history.py        ← 历史回填工具（15 天 37.9 万点；300s 网格幂等）
│   ├── fill_util.py           ← util_samples 负载/温度历史回填工具
│   └── report.py              ← 日报/月报/故障明细/TOP20/全量GPU/高温 CSV
├── sql/
│   ├── schema.sql             ← 建库建表（5 表）
│   └── migrate_20260827_gpu_temp.sql ← 存量库 util_samples 温度 4 列迁移（只跑一次）
├── rules/                     ← Prometheus 告警规则（2026-08-22 终版，线上 IB 规则略多）
│   ├── gpu-timer.yml          ← 空组（fault 检测已内迁 collector）
│   ├── gpu.yml                ← dcgm_gpu_alerts（GPU 告警）
│   ├── infiniband-exporter.yml← IB 告警（端口/卡数/误码率）
│   └── node-exporter.yml      ← 硬件故障组（内存 ECC/磁盘/CPU/风扇/电源等 9 条）
├── reports/                   ← 报表样例（daily/monthly/fault_detail 等 CSV，IP 已脱敏）
├── docs/
│   ├── 开发记录.md              ← 全周期开发记录（时间线/决策/踩坑/运维速查，IP 与口令已脱敏）
│   └── 设计文档-在线计时系统-v7.md ← 原始设计（v7 → 后续演进见开发记录）
└── tools/                     ← 部署/建图/方言工具 + dash4 大屏脚本（非计时核心，同仓存放）
    ├── deploy_top20.sh        ← 250 部署（TOP20 报表）
    ├── deploy_temp_report.sh  ← 250 部署（温度报表：同步→迁移→回填→重启→试生成）
    ├── superset_top20.py      ← Superset 建 TOP20 图表（CSRF+Session 版）
    ├── superset_gpu_temp.py   ← Superset 建 GPU 高温图表
    ├── superset_node_summary.py / superset_prom_node_summary.py ← 节点统计图表
    ├── prom_export.py         ← Prometheus 数据导出
    └── prometheus_dialect/    ← 自研 Superset Prometheus 方言终版留档（alerts 虚拟表等）
```

## 🚀 快速开始

```bash
# 1. 建库建表（250 mysql 容器；存量库用 sql/migrate_*.sql）
mysql -h 127.0.0.1 -uroot -p'<DB_PWD>' < sql/schema.sql

# 2. 构建 & 部署（142 构建 → 250 运行）
docker build -t gpu-timer:1.2 .
docker save gpu-timer:1.2 | gzip | ssh <250> 'gunzip | docker load'
ssh <250> 'docker run -d --name gpu-timer --network=host --restart=unless-stopped \
  -v /opt/gpu-timer/app:/app/app \
  -v /opt/gpu-timer/reports:/app/reports \
  -v /etc/localtime:/etc/localtime:ro \
  gpu-timer:1.2'

# 3. 本地调试（不需要容器）
pip install -r requirements.txt
python -m app.main          # 需可达 Prometheus(9090) 与 MySQL(3306)，配置见 app/config.py

# 4. 历史回填（可选）
python -m app.fill_history  # 15 天快照
python -m app.fill_util     # util_samples 负载/温度（首次部署后跑一次）
```

## ✅ 功能清单

- **P1 采集计时**：5min 10 条件判定 + 防抖事件 + 1h session 重建（幂等）+ 历史回填（300s 网格幂等）
- **P2 告警**：GPU/IB/硬件故障规则（HUP 热重载）→ alertmanager → 钉钉；fault 检测双轨（collector 写库 + 告警页）口径一致
- **P3 看板**：Superset dashboard 5「GPU 服务器在线计时」，9 图表（状态分布/趋势/排行/故障明细/在线台数/时长/CPU·GPU TOP20/GPU 高温卡明细）
- **P4 报表**：每日 5 份 + 每月月报 → CSV（§报表清单）
- **P5 负载统计**：util_samples 随采集落库，CPU 负载/GPU 利用率历史可回溯
- **P6 温度监控**：GPU 温度均/最热卡/序列号采集，>85℃ 每日明细报表 + 看板图表
- **权限**：gpuviewer 只读用户（gpuviewer / <GPUVIEWER_PWD>，仅 dashboard 5）；admin 密码 <SUPERSET_PWD>

## 📊 报表清单（/opt/gpu-timer/reports/）

| 调度 | 文件 | 内容 |
|---|---|---|
| 01:00 | daily_YYYY-MM-DD.csv | 各机当日三态时长/在线率 |
| 01:05 | fault_detail_YYYY-MM-DD.csv | 当日 fault/offline 时段明细 |
| 01:10 | cpu_top20_YYYY-MM-DD.csv | CPU 日均负载 TOP20 |
| 01:12 | full_gpu_YYYY-MM-DD.csv | GPU 日均利用率全量 89 台 |
| 01:14 | gpu_temp_over85_YYYY-MM-DD.csv | 前日 GPU >85℃ 机器明细（含最热卡编号/序列号） |
| 每月 1 日 02:00 | monthly_YYYY-MM.csv | 月度各机时长汇总 |

## 🔑 在线判定（10 条件）

online = ①IPMI 电源开 ∧ ②机器正常 ∧ ③GPU 在线 ∧ ④无不可纠正错误 ∧ ⑤无 XID ∧ ⑥IB 网络正常 ∧ ⑦IB 端口正常 ∧ ⑧无内存硬件故障（EDAC 1h 增长 >10 / uncorrectable >0 / HardwareCorrupted >0）∧ ⑨无磁盘硬件故障 ∧ ⑩无 CPU 硬件故障（IB 卡数量 ≥8）

- 任一失守且电源开 → **fault**（fault_reason 记录全部原因，可多值 `+` 拼接）
- 电源关/不可达 → **offline**；5min 采样 + 连续 2 点防抖（10min 确认翻转）
- 负载/温度指标顺带采集写 util_samples，不参与判定

## 📌 运维速查

```bash
docker logs -f gpu-timer          # 日志
docker restart gpu-timer          # 改代码后重启（代码挂载，无需重建镜像）
docker kill -s HUP prometheus     # 告警规则重载（验证 /api/v1/rules）
docker exec -i <mysql容器> mysql -uroot -p'<DB_PWD>' gpu_timer < x.sql   # 执行 SQL（注意 -i）
```

## 🔭 待办

项目归属分配（machines.project_id 预留）· 计费扩展（在线时长 × 单价）· 快照长期归档 · superset-fc 镜像重建固化 patch（pymysql/中文/方言/3D，均在容器可写层，rm 即丢）
