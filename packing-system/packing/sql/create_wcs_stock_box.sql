-- 接口库存箱子表（对应接口1 JSON 的 data[] 条目）
-- 库名：zhuangdb（请先 USE zhuangdb; 再执行，或直接整文件执行）
-- 无 up_to_standard：当前立库快照，有差异时由服务整表替换。

USE zhuangdb;

DROP TABLE IF EXISTS `wcs_stock_box`;

CREATE TABLE `wcs_stock_box` (
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
  COMMENT='WCS当前立库快照（接口1，按product_code集合全量替换）'
  ROW_FORMAT=Dynamic;
