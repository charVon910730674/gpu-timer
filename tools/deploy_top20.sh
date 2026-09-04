#!/bin/bash
# 部署 CPU/GPU TOP20 报表到 250：gpu-timer 代码 + util_samples 表 + 回填 + 重启 + Superset 报表
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

echo "[1/6] 同步代码 -> 250 (/opt/gpu-timer/app + /root/gpu-timer/app)"
sshpass -p "$PW" rsync -a --exclude __pycache__ -e "ssh $SSHOPT" "$SRC/app/" root@$H:/opt/gpu-timer/app/
sshpass -p "$PW" rsync -a --exclude __pycache__ -e "ssh $SSHOPT" "$SRC/app/" root@$H:/root/gpu-timer/app/
sshpass -p "$PW" scp $SSHOPT "$SRC/sql/schema.sql" root@$H:/root/gpu-timer/schema.sql
run_ssh "md5sum /opt/gpu-timer/app/*.py | md5sum"

echo "[2/6] 建 util_samples 表（schema.sql 幂等）"
run_ssh "MYSQLC=\$(docker ps --format '{{.Names}}' | grep -E '^mysql|mariadb' | head -1); echo mysql container=\$MYSQLC; docker exec -i \$MYSQLC mysql -uroot -p"$DBPW" gpu_timer" < "$SRC/sql/schema.sql" 2>&1 | grep -vi "using a password" || true

echo "[3/6] 回填 util 历史（Prometheus 保留期 15 天）"
run_ssh "docker exec gpu-timer python -m app.fill_util 15 2>&1 | tail -5"

echo "[4/6] 重启 gpu-timer 容器（加载新调度任务）"
run_ssh "docker restart gpu-timer && sleep 8 && docker logs --tail 3 gpu-timer"

echo "[5/6] 建 Superset 视图 v_util_full"
run_ssh "MYSQLC=\$(docker ps --format '{{.Names}}' | grep -E '^mysql|mariadb' | head -1); docker exec -i \$MYSQLC mysql -uroot -p"$DBPW" gpu_timer" <<'SQL' 2>&1 | grep -vi "using a password" || true
CREATE OR REPLACE VIEW v_util_full AS
SELECT u.id, u.machine_id, u.ts, u.cpu_load1, u.cpu_cores,
       u.gpu_util_avg, u.gpu_util_max, m.ip
FROM util_samples u
LEFT JOIN machines m ON m.id = u.machine_id;
SQL

echo "[6/6] Superset 数据集 + 2 图表（REST API）"
python3 "$SRC/tools/superset_top20.py"

echo "=== 部署完成 ==="
