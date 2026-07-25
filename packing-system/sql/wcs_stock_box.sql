/*
  wcs_stock_box — 当前立库快照（无达标字段）
  有差异时由服务整表替换；对比口径为 product_code 集合。
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `wcs_stock_box`;
CREATE TABLE `wcs_stock_box`  (
  `id` bigint(0) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `box_spec` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL COMMENT '箱子规格 (length,width,height,box_type)',
  `case_type` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT '' COMMENT '托盘型号 case_type',
  `target_num` int(0) NULL DEFAULT 1 COMMENT '数量 target_num',
  `order_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT '' COMMENT '订单号 order_id',
  `case_group` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT '0' COMMENT '拼箱组号 case_group',
  `product_code` bigint(0) NOT NULL COMMENT '产品编码 product_code（一箱一码，唯一）',
  `priority` int(0) NULL DEFAULT 0 COMMENT '优先级 priority',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_product_code`(`product_code`) USING BTREE,
  INDEX `idx_order_id`(`order_id`) USING BTREE,
  INDEX `idx_case_type`(`case_type`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = 'WCS当前立库快照' ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;
