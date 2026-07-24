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

 Date: 24/07/2026 01:58:38
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for wcs_plc_queue
-- ----------------------------
DROP TABLE IF EXISTS `wcs_plc_queue`;
CREATE TABLE `wcs_plc_queue`  (
  `id` bigint(0) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `box_unique_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '托盘方案唯一ID',
  `seq` int(0) UNSIGNED NOT NULL COMMENT '盘内序号',
  `product_code` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '箱子编号（展示用）',
  `item_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '计划内箱子 id',
  `state` tinyint(0) UNSIGNED NOT NULL COMMENT '旋转状态 1/2（写入命令时快照）',
  `target_orientation_deg` tinyint(0) UNSIGNED NULL DEFAULT NULL COMMENT '目标姿态 0/90',
  `camera_orientation_deg` tinyint(0) UNSIGNED NULL DEFAULT NULL COMMENT '相机姿态 0/90',
  `command_json` json NOT NULL COMMENT '已构造的 DB19 字段',
  `status` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending' COMMENT 'pending/sent/failed',
  `send_note` varchar(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '发送结果说明',
  `created_at` datetime(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  `sent_at` datetime(0) NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_plc_unique_seq`(`box_unique_id`, `seq`) USING BTREE,
  INDEX `idx_plc_status_created`(`status`, `created_at`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 4 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = 'PLC 命令队列：state 就绪后自动入队下传；界面可应急补发' ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;
