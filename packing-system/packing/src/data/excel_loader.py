"""
Excel 数据加载与箱子预处理

把原 zhuangxiang.preprocess_data 拆出来，移除对全局常量的隐式依赖。
"""

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from src.config.constants import (
    SMALL_BOX_BMS_SHEET,
    SMALL_BOX_SOURCE_FILE,
    SMALL_BOX_SOURCE_SHEET,
)
from src.utils.case_group import normalize_case_group


def load_boxes(filepath: Optional[str] = None) -> Optional[List[Dict]]:
    """加载箱子数据并预处理。

    Args:
        filepath: Excel 文件路径；None 时使用 SMALL_BOX_SOURCE_FILE 默认值。

    Returns:
        箱子字典列表；文件不存在时返回 None。
    """
    if filepath is None:
        filepath = SMALL_BOX_SOURCE_FILE
    else:
        filepath = Path(filepath)

    try:
        excel = pd.ExcelFile(filepath)
        source_sheet = SMALL_BOX_SOURCE_SHEET
        if source_sheet not in excel.sheet_names:
            for sheet_name in excel.sheet_names:
                if sheet_name not in {SMALL_BOX_BMS_SHEET, "说明"}:
                    source_sheet = sheet_name
                    break
        df_tasks = pd.read_excel(filepath, sheet_name=source_sheet)
        df_bms = pd.read_excel(filepath, sheet_name=SMALL_BOX_BMS_SHEET)
    except FileNotFoundError:
        print(f"错误：未找到文件 '{filepath}'。")
        return None

    df_bms = df_bms.set_index('包装规格代码')
    raw_ids = df_tasks['箱子序号'].astype(str)
    duplicated_raw_ids = set(raw_ids[raw_ids.duplicated(keep=False)])
    all_boxes = []
    for row_idx, row in df_tasks.iterrows():
        original_box_id = row['箱子序号']
        box_id = (
            f"{original_box_id}__row{row_idx}"
            if str(original_box_id) in duplicated_raw_ids
            else original_box_id
        )
        box_type = row['Box类型']
        raw_weight = row.get('总重量', 0)
        weight = pd.to_numeric(raw_weight, errors='coerce')
        if pd.isna(weight):
            weight = 0.0
        min_pack_multiple = (
            df_bms.loc[box_type, '最小包装量的倍数']
            if box_type in df_bms.index else 0
        )
        sales_order_no = row.get('销售订单号', 'UNKNOWN_ORDER')
        if pd.isna(sales_order_no) or str(sales_order_no).strip() == "":
            sales_order_no = 'UNKNOWN_ORDER'
        length = pd.to_numeric(row['箱子长'], errors='coerce')
        width = pd.to_numeric(row['箱子宽'], errors='coerce')
        height = pd.to_numeric(row['箱子高'], errors='coerce')
        all_boxes.append({
            "id": box_id,
            "original_box_id": original_box_id,
            "type": box_type,
            "length": float(length) if pd.notna(length) else 0.0,
            "width": float(width) if pd.notna(width) else 0.0,
            "height": float(height) if pd.notna(height) else 0.0,
            "weight": float(weight),
            "min_pack_multiple": float(min_pack_multiple),
            "pallet_type": row['Case类型'],
            "sales_order_no": str(sales_order_no),
            # case_group 同组约束（可选列，缺列/空值＝0＝无约束）：非 0 时该箱
            # 只能与相同 case_group 的箱子同托盘。正式接入走系统接口同名字段。
            "case_group": normalize_case_group(row.get('case_group', 0)),
            "pallet_dims": {
                "length": row['托盘长'],
                "width": row['托盘宽'],
                "height": row['托盘高'],
            },
        })

    df_boxes = pd.DataFrame(all_boxes)
    df_boxes['包装规格代码'] = df_boxes['type'].astype(str)

    all_boxes = df_boxes.to_dict('records')
    for box in all_boxes:
        box.setdefault('volume', box['length'] * box['width'] * box['height'])
        box.setdefault('weight', float(box.get('weight', 0) or 0))
    return all_boxes
