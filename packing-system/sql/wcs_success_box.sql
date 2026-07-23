-- 达标托盘箱子明细表
-- 一行 = 一个箱子；同一托盘的多箱共用同一个 box_unique_id
-- 库名与 packing_config.yaml 中 database.database 保持一致（默认 zhuangdb）
--
-- 若表已存在且缺 product_code，可执行：
--   ALTER TABLE wcs_success_box
--     ADD COLUMN product_code BIGINT NULL COMMENT '单箱唯一产品码' AFTER case_type,
--     ADD UNIQUE KEY uk_product_code (product_code);

CREATE DATABASE IF NOT EXISTS `zhuangdb`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `zhuangdb`;

DROP TABLE IF EXISTS `wcs_success_box`;

CREATE TABLE `wcs_success_box` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `box_unique_id` CHAR(32) NOT NULL COMMENT '托盘方案唯一ID（一盘多箱相同，对方按此查询）',
  `seq` INT UNSIGNED NOT NULL COMMENT '盘内执行序号（从1开始）',
  `raw_length` DOUBLE NOT NULL COMMENT '箱子真实长度 mm',
  `raw_width` DOUBLE NOT NULL COMMENT '箱子真实宽度 mm',
  `raw_height` DOUBLE NOT NULL COMMENT '箱子真实高度 mm',
  `pos_x` DOUBLE NOT NULL COMMENT '放置坐标 x mm',
  `pos_y` DOUBLE NOT NULL COMMENT '放置坐标 y mm',
  `pos_z` DOUBLE NOT NULL COMMENT '放置坐标 z mm',
  `stack_height_before` DOUBLE NOT NULL DEFAULT 0 COMMENT '放置当前箱之前的垛型最高顶面 mm',
  `state` TINYINT UNSIGNED NOT NULL COMMENT '朝向：1=不转，2=转（90°）；当前固定写 1',
  `pallet_id` VARCHAR(64) NULL COMMENT '算法内部托盘编号（可选，便于人对账）',
  `order_id` VARCHAR(64) NULL COMMENT '销售订单号 sales_order_no',
  `case_type` VARCHAR(32) NULL COMMENT '托盘类型 pallet_type，如 MH423C',
  `product_code` BIGINT NOT NULL COMMENT '单箱唯一产品码；WCS 有则用库存码，Excel 缺码时写随机内部码',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '写入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_box_unique_seq` (`box_unique_id`, `seq`),
  UNIQUE KEY `uk_product_code` (`product_code`),
  KEY `idx_box_unique_id` (`box_unique_id`),
  KEY `idx_created_at` (`created_at`),
  CONSTRAINT `chk_state` CHECK (`state` IN (1, 2))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='达标托盘箱子明细：执行规划完成后有达标盘则按箱插入';
