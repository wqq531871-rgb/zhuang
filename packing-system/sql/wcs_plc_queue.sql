-- PLC 下发队列表（方案 C：先构造入队，界面按钮再发送）
-- 一行 = 一箱的已构造 DB19 命令；status: pending / sent / failed
-- 写入时机：接口4 判转并更新 wcs_success_box.state 成功后立刻构造入队
-- 发送时机：仪表盘「现场码垛」点「发送到 PLC」（当前为桩发送：落日志并标 sent）

CREATE DATABASE IF NOT EXISTS `zhuangdb`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `zhuangdb`;

CREATE TABLE IF NOT EXISTS `wcs_plc_queue` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `box_unique_id` CHAR(32) NOT NULL COMMENT '托盘方案唯一ID',
  `seq` INT UNSIGNED NOT NULL COMMENT '盘内序号',
  `product_code` VARCHAR(255) NULL COMMENT '箱子编号（展示用）',
  `item_id` VARCHAR(128) NULL COMMENT '计划内箱子 id',
  `state` TINYINT UNSIGNED NOT NULL COMMENT '旋转状态 1/2（写入命令时快照）',
  `target_orientation_deg` TINYINT UNSIGNED NULL COMMENT '目标姿态 0/90',
  `camera_orientation_deg` TINYINT UNSIGNED NULL COMMENT '相机姿态 0/90',
  `command_json` JSON NOT NULL COMMENT '已构造的 DB19 字段',
  `status` VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending/sent/failed',
  `send_note` VARCHAR(512) NULL COMMENT '发送结果说明',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `sent_at` DATETIME NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_plc_unique_seq` (`box_unique_id`, `seq`),
  KEY `idx_plc_status_created` (`status`, `created_at`),
  CONSTRAINT `chk_plc_state` CHECK (`state` IN (1, 2)),
  CONSTRAINT `chk_plc_status` CHECK (`status` IN ('pending', 'sent', 'failed'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='PLC 命令队列：构造后待界面确认发送';
