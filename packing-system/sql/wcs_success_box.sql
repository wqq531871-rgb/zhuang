/*
 Navicat Premium Data Transfer

 Source Server         : localhost
 Source Server Type    : MySQL
 Source Server Version : 80030
 Source Host           : localhost:3306
 Source Schema         : zhuangdb

 Target Server Type    : MySQL
 Target Server Version : 80030
 File Encoding         : 65001

 Date: 24/07/2026 10:10:12
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for wcs_success_box
-- ----------------------------
DROP TABLE IF EXISTS `wcs_success_box`;
CREATE TABLE `wcs_success_box`  (
  `id` bigint(0) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `box_unique_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '托盘方案唯一ID（一盘多箱相同，对方按此查询）',
  `seq` int(0) UNSIGNED NOT NULL COMMENT '盘内执行序号（从1开始）',
  `raw_length` double NOT NULL COMMENT '箱子真实长度 mm',
  `raw_width` double NOT NULL COMMENT '箱子真实宽度 mm',
  `raw_height` double NOT NULL COMMENT '箱子真实高度 mm',
  `pos_x` double NOT NULL COMMENT '放置坐标 x mm',
  `pos_y` double NOT NULL COMMENT '放置坐标 y mm',
  `pos_z` double NOT NULL COMMENT '放置坐标 z mm',
  `stack_height_before` double NOT NULL DEFAULT 0 COMMENT '放置当前箱之前的垛型最高顶面 mm',
  `state` tinyint(0) UNSIGNED NULL DEFAULT NULL COMMENT '0=异型(非同类型) 1=同型不转 2=同型转90°；初始空',
  `pallet_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '算法内部托盘编号（可选，便于人对账）',
  `order_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '销售订单号 sales_order_no',
  `case_type` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '托盘类型 pallet_type，如 MH423C',
  `created_at` datetime(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0) COMMENT '写入时间',
  `product_code` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '箱子唯一编号',
  `is_send` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '是否下传\r\n1：已下传\r\n2：未下传',
  `case_group` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `camera_length` double NULL DEFAULT NULL COMMENT '相机测长 mm（托盘坐标系轴向）',
  `camera_width` double NULL DEFAULT NULL COMMENT '相机测宽 mm',
  `camera_height` double NULL DEFAULT NULL COMMENT '相机测高 mm',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_box_unique_seq`(`box_unique_id`, `seq`) USING BTREE,
  INDEX `idx_box_unique_id`(`box_unique_id`) USING BTREE,
  INDEX `idx_created_at`(`created_at`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '达标托盘箱子明细：每次计算结束后有达标盘则按箱插入' ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;
