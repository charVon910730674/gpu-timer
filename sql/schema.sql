-- GPU 服务器在线计时系统 v7 schema
CREATE DATABASE IF NOT EXISTS gpu_timer DEFAULT CHARSET utf8mb4;

USE gpu_timer;

CREATE TABLE IF NOT EXISTS machines (
  id INT AUTO_INCREMENT PRIMARY KEY,
  hostname VARCHAR(64),
  ip VARCHAR(32) NOT NULL UNIQUE,
  spec VARCHAR(32) DEFAULT '8xH100',
  power_source ENUM('ipmi','probe') DEFAULT 'ipmi',
  project_id INT,
  enabled TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS power_snapshots (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  machine_id INT NOT NULL,
  ts DATETIME NOT NULL,
  state ENUM('online','fault','offline') NOT NULL,
  power_on TINYINT,
  machine_ok TINYINT,
  gpu_online TINYINT,
  gpu_uncorrectable TINYINT,
  xid_error INT,
  ib_link_ok TINYINT,
  ib_port_ok TINYINT,
  mem_fault TINYINT,
  disk_fault TINYINT,
  cpu_fault TINYINT,
  ib_all_ok TINYINT,
  fault_reason VARCHAR(64),
  src ENUM('ipmi','probe'),
  UNIQUE KEY uq_machine_ts (machine_id, ts),
  KEY idx_ts (ts),
  KEY idx_state (state)
);

CREATE TABLE IF NOT EXISTS power_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  machine_id INT NOT NULL,
  event_type ENUM('online','fault','offline') NOT NULL,
  fault_reason VARCHAR(64),
  ts DATETIME NOT NULL,
  src ENUM('ipmi','probe'),
  UNIQUE KEY uq_machine_evt_ts (machine_id, event_type, ts),
  KEY idx_machine_ts (machine_id, ts)
);

-- 负载/利用率采样：随 collect 每 5 分钟一条，供 TOP10 报表聚合
CREATE TABLE IF NOT EXISTS util_samples (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  machine_id INT NOT NULL,
  ts DATETIME NOT NULL,
  cpu_load1 DECIMAL(8,3),       -- node_load1 1 分钟平均负载
  cpu_cores INT,                -- 逻辑核数（每核负载归一化用）
  gpu_util_avg DECIMAL(6,2),    -- 该机全部 GPU 利用率平均 (0-100)
  gpu_util_max DECIMAL(6,2),    -- 该机 GPU 利用率最大 (0-100)
  gpu_temp_avg DECIMAL(6,2),    -- 该机全部 GPU 温度平均 (℃)
  gpu_temp_max DECIMAL(6,2),    -- 该机 GPU 温度最大 (℃)
  gpu_temp_hot_idx VARCHAR(8),  -- 最热 GPU 编号（dcgm label gpu）
  gpu_temp_hot_uuid VARCHAR(64),-- 最热 GPU 序列号（dcgm label UUID）
  UNIQUE KEY uq_machine_ts (machine_id, ts),
  KEY idx_ts (ts)
);

CREATE TABLE IF NOT EXISTS sessions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  machine_id INT NOT NULL,
  state ENUM('online','fault','offline') NOT NULL,
  fault_reason VARCHAR(64),
  start_time DATETIME NOT NULL,
  end_time DATETIME NOT NULL,
  duration_hours DECIMAL(10,4) NOT NULL,
  ongoing TINYINT DEFAULT 0,
  UNIQUE KEY uq_machine_state_start (machine_id, state, start_time),
  KEY idx_machine_start (machine_id, start_time)
);
