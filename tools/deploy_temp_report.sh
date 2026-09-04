#!/bin/bash
# 部署 GPU 高温日报到 250：代码同步 + util_samples 加温度列 + 回填 + 重启 + 试生成
# 前置：目标机（250）可达（SSH 22）；本机 workspace/gpu-timer 已含新代码
set -euo pipefail

# 凭据不入库：从环境变量或 /root/.gpu-timer-secrets（chmod 600）读取
#   GPU_TIMER_HOST / GPU_TIMER_SSH_PW / MYSQL_PASSWORD
if [ -f /root/.gpu-timer-secrets ]; then . /root/.gpu-timer-secrets; fi
H="${GPU_TIMER_HOST:?未设置 GPU_TIMER_HOST（可写入 /root/.gpu-timer-secrets）}"
PW="${GPU_TIMER_SSH_PW:?未设置 GPU_TIMER_SSH_PW}"
DBPW="${MYSQL_PASSWORD:?未设置 MYSQL_PASSWORD}"
SSHOPT="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
SRC=/root/.openclaw/workspace/gpu-timer

run_ssh() { sshpass -p "$PW" ssh $SSHOPT root@$H "$@"; }

echo "[1/5] 同步代码 -> 250 (/opt/gpu-timer/app + /root/gpu-timer/app)"
sshpass -p "$PW" rsync -a --exclude __pycache__ -e "ssh $SSHOPT" "$SRC/app/" root@$H:/opt/gpu-timer/app/
sshpass -p "$PW" rsync -a --exclude __pycache__ -e "ssh $SSHOPT" "$SRC/app/" root@$H:/root/gpu-timer/app/
sshpass -p "$PW" scp $SSHOPT "$SRC/sql/migrate_20260827_gpu_temp.sql" root@$H:/opt/gpu-timer/migrate_20260827_gpu_temp.sql
run_ssh "md5sum /opt/gpu-timer/app/*.py | md5sum"

echo "[2/5] util_samples 增加温度列（迁移 SQL，仅执行一次）"
run_ssh "MYSQLC=\$(docker ps --format '{{.Names}}' | grep -E '^mysql|mariadb' | head -1); echo mysql container=\$MYSQLC; docker exec -i \$MYSQLC mysql -uroot -p"$DBPW" gpu_timer" < "$SRC/sql/migrate_20260827_gpu_temp.sql" 2>&1 | grep -vi "using a password" || true

echo "[3/5] 回填 GPU 温度历史（ON DUPLICATE KEY UPDATE 只补温度列，不动旧数据）"
run_ssh "docker exec gpu-timer python -m app.fill_util 15 2>&1 | tail -8"

echo "[4/5] 重启 gpu-timer 容器（加载新调度任务 01:14）"
run_ssh "docker restart gpu-timer && sleep 8 && docker logs --tail 3 gpu-timer"

echo "[5/5] 试生成昨日高温报表（无数据则生成空表头 CSV，属正常）"
run_ssh "docker exec gpu-timer python -c 'from app import report; print(report.gen_gpu_temp_over85())' && docker exec gpu-timer ls -la /app/reports/ | tail -5"

echo "=== 部署完成 ==="
