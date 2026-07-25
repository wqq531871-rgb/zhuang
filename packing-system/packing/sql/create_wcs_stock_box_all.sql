-- 立库历史全量表（接口1 见过的 product_code 只增不减）
-- 与 wcs_stock_box 字段基本一致，但无 up_to_standard。

USE zhuangdb;

CREATE TABLE IF NOT EXISTS `wcs_stock_box_all` (
  `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `box_spec` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL COMMENT '箱子规格 (length,width,height,box_type[,weight])',
  `case_type` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT '' COMMENT '托盘型号 case_type',
  `target_num` int NULL DEFAULT 1 COMMENT '数量 target_num',
  `order_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT '' COMMENT '订单号 order_id',
  `case_group` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT '0' COMMENT '拼箱组号 case_group',
  `product_code` bigint NOT NULL COMMENT '产品编码 product_code（一箱一码，唯一）',
  `priority` int NULL DEFAULT 0 COMMENT '优先级 priority',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_product_code` (`product_code`) USING BTREE,
  KEY `idx_order_id` (`order_id`) USING BTREE,
  KEY `idx_case_type` (`case_type`) USING BTREE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='WCS立库历史全量（接口1 追加，不删除）'
  ROW_FORMAT=Dynamic;
