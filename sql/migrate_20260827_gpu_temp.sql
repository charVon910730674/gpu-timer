-- gpu-timer 迁移：util_samples 增加 GPU 温度列（2026-08-27）
-- 适用：已有 util_samples 表的存量库（新库直接跑 schema.sql 即可，勿重复执行本文件）
-- 用法: mysql -h127.0.0.1 -uroot -p'<DB_PWD>' gpu_timer < migrate_20260827_gpu_temp.sql

ALTER TABLE util_samples
  ADD COLUMN gpu_temp_avg DECIMAL(6,2) NULL AFTER gpu_util_max,
  ADD COLUMN gpu_temp_max DECIMAL(6,2) NULL AFTER gpu_temp_avg,
  ADD COLUMN gpu_temp_hot_idx VARCHAR(8) NULL AFTER gpu_temp_max,
  ADD COLUMN gpu_temp_hot_uuid VARCHAR(64) NULL AFTER gpu_temp_hot_idx;
