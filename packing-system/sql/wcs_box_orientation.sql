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

 Date: 24/07/2026 01:58:33
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for wcs_box_orientation
-- ----------------------------
DROP TABLE IF EXISTS `wcs_box_orientation`;
CREATE TABLE `wcs_box_orientation`  (
  `id` bigint(0) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `box_unique_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '托盘方案唯一ID',
  `seq` int(0) UNSIGNED NOT NULL COMMENT '盘内执行序号（从1开始）',
  `item_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '计划内箱子 id，绑相机 box_id',
  `product_code` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '库存/内部 product_code（可选）',
  `suction_orientation` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '如 cup_600x_800y / cup_800x_600y',
  `suction_cup_x_size` double NULL DEFAULT NULL COMMENT '吸盘 X 尺寸 mm',
  `suction_cup_y_size` double NULL DEFAULT NULL COMMENT '吸盘 Y 尺寸 mm',
  `target_orientation_deg` tinyint(0) UNSIGNED NOT NULL COMMENT '目标姿态：0 或 90',
  `created_at` datetime(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0) COMMENT '写入时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_orient_unique_seq`(`box_unique_id`, `seq`) USING BTREE,
  INDEX `idx_orient_item_id`(`item_id`) USING BTREE,
  INDEX `idx_orient_created_at`(`created_at`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 167 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '每箱目标姿态：接口4到达后与相机角比较，更新 wcs_success_box.state' ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;
