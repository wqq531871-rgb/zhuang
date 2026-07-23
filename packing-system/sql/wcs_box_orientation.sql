-- 旋转判断用：每箱目标吸盘姿态（供接口4 boxarrive 读取）
-- 一行 = 一个箱子；与 wcs_success_box 共用 (box_unique_id, seq)
-- 库名与 packing_config.yaml 中 database.database 保持一致（默认 zhuangdb）
--
-- 写入时机：执行规划完成后，与 wcs_success_box 同期写入 SUCCESS 盘
-- 读取时机：WCS POST /adaptor/api/wcs/boxarrive（接口4）按箱到达时

CREATE DATABASE IF NOT EXISTS `zhuangdb`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `zhuangdb`;

CREATE TABLE IF NOT EXISTS `wcs_box_orientation` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `box_unique_id` CHAR(32) NOT NULL COMMENT '托盘方案唯一ID',
  `seq` INT UNSIGNED NOT NULL COMMENT '盘内执行序号（从1开始）',
  `item_id` VARCHAR(128) NULL COMMENT '计划内箱子 id，绑相机 box_id',
  `product_code` VARCHAR(255) NULL COMMENT '库存/内部 product_code（可选）',
  `suction_orientation` VARCHAR(64) NULL COMMENT '如 cup_600x_800y / cup_800x_600y',
  `suction_cup_x_size` DOUBLE NULL COMMENT '吸盘 X 尺寸 mm',
  `suction_cup_y_size` DOUBLE NULL COMMENT '吸盘 Y 尺寸 mm',
  `target_orientation_deg` TINYINT UNSIGNED NOT NULL COMMENT '目标姿态：0 或 90',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '写入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_orient_unique_seq` (`box_unique_id`, `seq`),
  KEY `idx_orient_item_id` (`item_id`),
  KEY `idx_orient_created_at` (`created_at`),
  CONSTRAINT `chk_target_orientation_deg`
    CHECK (`target_orientation_deg` IN (0, 90))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='每箱目标姿态：接口4到达后与相机角比较，更新 wcs_success_box.state';
