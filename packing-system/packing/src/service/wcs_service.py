"""WCS 接口装箱常驻服务（HTTP 服务壳）。

接口持续模式按单一串行周期运行：

1. 每轮记录拉取开始时间并 POST 接口 1；
   原始 JSON → ``input/raw/``；
   过滤 MH423C 后：
   - ``wcs_stock_box``：按 product_code 集合对比；有差异则整表清空后全量插入，
     并在本轮触发装箱；完全一致则不动、不装箱；
   - ``wcs_stock_box_all``：历史全量追加（新码插入、已有跳过，不删除）。

2. 库存有变化时，当前线程读取库存并完成装箱；计算期间不再拉取。
3. 计算结束后只等待本轮 ``download_interval`` 的剩余时间；若本轮已经超时，
   立即开始下一次拉取。

可选：装箱结果推送接口 2（由 ``_PUSH_PLAN_TO_WCS`` 控制）。
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
import urllib3

from src.adapter import (
    default_pallet_dims_map,
    load_bms_map,
    report_to_plan_result,
    stock_to_boxes,
)
from src.adapter.wcs_adapter import (
    WcsPlanResult,
    build_stock_request,
    coerce_product_code,
)
from src.config import (
    DATA_DIR,
    DEFAULT_PACKING_CONFIG,
    INPUT_DIR,
    OUTPUT_DIR,
    WORKSPACE_ROOT,
    ConfigLoader,
)
from src.main.report_persister import NullReportPersister
from src.main.output_split import (
    report_has_success_pallets,
    resolve_report_bucket_dir,
)
from src.service.stock_db import (
    WcsStockAllRepository,
    WcsStockRepository,
    load_database_config,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 接口模式下仅处理该托盘型号；其余 case_type 在落库前剔除。
_SUPPORTED_CASE_TYPE = "MH423C"
# False=只本地装箱/落盘，不向接口 2 推送结果（调试用，恢复推送改 True）。
_PUSH_PLAN_TO_WCS = False
# UI 识别此标记后按「停止」处理（与点击停止按钮同效）。
WCS_STOP_MARKER = "[WCS-STOP]"


def _resolve_yaml_path(config_path: Optional[Path] = None) -> Optional[Path]:
    """显式 --config > 仓库根 packing_config.yaml。"""
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            return path
    if DEFAULT_PACKING_CONFIG.exists():
        return DEFAULT_PACKING_CONFIG
    return None


def _require_data_source_raw(config_path: Optional[Path] = None) -> dict:
    """只从 packing_config.yaml 读 data_source；无代码内第二套配置。"""
    yaml_path = _resolve_yaml_path(config_path)
    if yaml_path is None:
        raise FileNotFoundError(
            f"找不到配置文件：请提供 --config，或确保存在 {DEFAULT_PACKING_CONFIG}"
        )
    try:
        raw = (ConfigLoader(yaml_path).config_data or {}).get("data_source") or {}
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f"读取 data_source 失败（{yaml_path}）：{exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"配置缺少 data_source 段：{yaml_path}")
    return raw


@dataclass(frozen=True)
class DataSourceConfig:
    mode: str
    use_real_api: bool
    api_base_url: str
    api_fallback_url: str
    stock_path: str
    plan_path: str
    download_interval: int
    input_dir: Path
    bms_reference_file: Path
    output_dir: Path
    reqpallet_path: str = "/api/wcs/reqpallet"

    @property
    def effective_api_base_url(self) -> str:
        """真实接口开 → api_base_url；关 → Postman 备用。"""
        if self.use_real_api:
            return self.api_base_url
        return self.api_fallback_url or self.api_base_url

    def stock_url(self) -> str:
        return f"{self.effective_api_base_url.rstrip('/')}{self.stock_path}"

    def plan_url(self) -> str:
        return f"{self.effective_api_base_url.rstrip('/')}{self.plan_path}"

    def reqpallet_url(self) -> str:
        return f"{self.effective_api_base_url.rstrip('/')}{self.reqpallet_path}"


@dataclass(frozen=True)
class PackRunResult:
    """One WCS packing round outcome for service-level stop decisions."""

    executed: bool
    success_pallets: int = 0
    report_path: Optional[Path] = None


def load_data_source_config(config_path: Optional[Path] = None) -> DataSourceConfig:
    """从 yaml 的 data_source 段读取接口模式配置（单一来源 packing_config.yaml）。"""
    raw = _require_data_source_raw(config_path)
    rel_input = str(raw.get("input_dir") or "input")
    bms_rel = str(raw.get("bms_reference_file") or "")
    if not bms_rel:
        raise ValueError("data_source.bms_reference_file 未配置")
    input_path = Path(rel_input)
    if not input_path.is_absolute():
        input_path = (INPUT_DIR if rel_input in {"input", "."} else WORKSPACE_ROOT / rel_input)
    api_base = str(raw.get("api_base_url") or "").strip()
    if not api_base:
        raise ValueError("data_source.api_base_url 未配置")
    stock_path = str(raw.get("stock_path") or "").strip()
    plan_path = str(raw.get("plan_path") or "").strip()
    if not stock_path or not plan_path:
        raise ValueError("data_source.stock_path / plan_path 未配置")
    if not stock_path.startswith("/"):
        stock_path = "/" + stock_path
    if not plan_path.startswith("/"):
        plan_path = "/" + plan_path
    reqpallet_path = str(
        raw.get("reqpallet_path") or "/api/wcs/reqpallet"
    ).strip()
    if not reqpallet_path.startswith("/"):
        reqpallet_path = "/" + reqpallet_path
    return DataSourceConfig(
        mode=str(raw.get("mode") or "api").strip().lower(),
        use_real_api=bool(raw.get("use_real_api", True)),
        api_base_url=api_base,
        api_fallback_url=str(raw.get("api_fallback_url") or "").strip(),
        stock_path=stock_path,
        plan_path=plan_path,
        download_interval=max(1, int(raw.get("download_interval") or 200)),
        input_dir=input_path.resolve(),
        bms_reference_file=(DATA_DIR / bms_rel).resolve(),
        output_dir=OUTPUT_DIR.resolve(),
        reqpallet_path=reqpallet_path,
    )


def _load_db_config_from_yaml(config_path: Optional[Path] = None):
    """只从 packing_config.yaml（或 --config）读 database 段，无代码内密码副本。"""
    yaml_path = _resolve_yaml_path(config_path)
    raw = {}
    if yaml_path is not None:
        try:
            raw = (ConfigLoader(yaml_path).config_data or {}).get("database") or {}
        except (OSError, ValueError, KeyError):
            raw = {}
    return load_database_config(raw)


def fetch_stock_response(base_url: str, stock_path: str, timeout: int = 30) -> Dict:
    """POST 接口 1，返回完整响应体 {code, msg, data}。"""
    path = stock_path if stock_path.startswith("/") else f"/{stock_path}"
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.post(
        url,
        json=build_stock_request(),
        timeout=timeout,
        verify=False,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(
            f"接口 1 返回错误: code={body.get('code')}, msg={body.get('msg')}"
        )
    return body


def push_plan_result(
    base_url: str, cases: List[Dict], plan_path: str, timeout: int = 60
) -> Dict:
    """POST 接口 2，发送 case 数组，返回 WCS 响应体。"""
    path = plan_path if plan_path.startswith("/") else f"/{plan_path}"
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.post(url, json=cases, timeout=timeout, verify=False)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(
            f"接口 2 返回错误: code={body.get('code')}, msg={body.get('msg')}"
        )
    return body


def build_reqpallet_payload(
    arrival: Dict,
    wcs_case: Dict,
    *,
    empty_flag: bool = False,
) -> Dict:
    """Build interface 4.5 from the physical 4.6 pallet and one packed case."""
    identity = {
        key: str(arrival.get(key) or "").strip()
        for key in ("robot_id", "station_id", "pallet_code")
    }
    missing = [key for key, value in identity.items() if not value]
    if missing:
        raise ValueError(f"4.6 缺少字段：{', '.join(missing)}")

    source_layers = wcs_case.get("layers") or []
    layers = []
    for layer in source_layers:
        cartons = []
        for carton in (layer.get("cartons") or []):
            cartons.append(
                {
                    "seq": int(carton.get("seq") or 0),
                    "length": carton.get("length"),
                    "width": carton.get("width"),
                    "height": carton.get("height"),
                    "product_code": str(
                        carton.get("product_code") or ""
                    ).strip(),
                }
            )
        if cartons:
            layers.append({"cartons": cartons})
    if not empty_flag and not layers:
        raise ValueError("码垛完成时 case_data 不能为空")

    box_unique_id = str(wcs_case.get("box_unique_id") or "").strip()
    if not empty_flag and not box_unique_id:
        raise ValueError("4.5 case_data 缺少 box_unique_id")
    case_data = []
    if not empty_flag:
        case_data.append(
            {
                "box_index": int(wcs_case.get("box_index") or 1),
                "box_unique_id": box_unique_id,
                "case_group": str(wcs_case.get("case_group") or "0"),
                "height": 0,
                "layers": layers,
            }
        )

    case_type = str(arrival.get("case_type") or "").strip()
    if not case_type:
        case_type = str(wcs_case.get("case_type") or "").strip()
    if not case_type:
        raise ValueError("4.5 缺少 case_type")

    return {
        **identity,
        "case_type": case_type,
        "empty_flag": bool(empty_flag),
        "case_data": case_data,
    }


def push_reqpallet(
    base_url: str,
    payload: Dict,
    reqpallet_path: str,
    timeout: int = 30,
) -> Dict:
    """POST interface 4.5 and require a successful WCS business response."""
    path = (
        reqpallet_path
        if str(reqpallet_path).startswith("/")
        else f"/{reqpallet_path}"
    )
    url = f"{str(base_url).rstrip('/')}{path}"
    resp = requests.post(
        url,
        json=payload,
        timeout=timeout,
        verify=False,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(
            f"接口 4.5 返回错误: code={body.get('code')}, msg={body.get('msg')}"
        )
    return body


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def select_wcs_plan_result(report: Dict, execution_outcome) -> WcsPlanResult:
    """Use the execution bundle only when both WCS artifacts are available."""

    if not getattr(execution_outcome, "succeeded", False):
        return report_to_plan_result(report)
    wcs_path = getattr(execution_outcome, "wcs_path", None)
    map_path = getattr(execution_outcome, "wcs_map_path", None)
    if wcs_path is None or map_path is None:
        return report_to_plan_result(report)
    cases = json.loads(Path(wcs_path).read_text(encoding="utf-8"))
    plan_map = json.loads(Path(map_path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not isinstance(plan_map, dict):
        raise ValueError("execution WCS artifacts have invalid JSON shapes")
    try:
        case_ids = {str(case["box_unique_id"]) for case in cases}
    except (KeyError, TypeError) as exc:
        raise ValueError("execution case is missing box_unique_id") from exc
    if case_ids != {str(unique_id) for unique_id in plan_map}:
        raise ValueError("execution cases and map have different box_unique_id sets")
    return WcsPlanResult(cases=cases, plan_by_unique_id=plan_map)


def _filter_mh423c(stock_entries: List[Dict]):
    """保留 case_type=MH423C；返回 (kept, dropped_count, dropped_types)。"""
    kept = [
        e for e in stock_entries
        if str(e.get("case_type") or "").strip() == _SUPPORTED_CASE_TYPE
    ]
    dropped = len(stock_entries) - len(kept)
    dropped_types = sorted({
        str(e.get("case_type"))
        for e in stock_entries
        if str(e.get("case_type") or "").strip() != _SUPPORTED_CASE_TYPE
    })
    return kept, dropped, dropped_types


def _split_positive_dimension_entries(
    stock_entries: List[Dict],
) -> tuple[List[Dict], List[Dict]]:
    """按严格正数且有限的长宽高拆分有效与非法库存记录。"""
    valid: List[Dict] = []
    invalid: List[Dict] = []
    for entry in stock_entries:
        try:
            for key in ("length", "width", "height"):
                value = entry.get(key)
                if isinstance(value, bool):
                    raise ValueError(f"{key} must not be bool")
                number = float(value)
                if not math.isfinite(number) or number <= 0:
                    raise ValueError(f"{key} must be positive and finite")
        except (TypeError, ValueError, OverflowError):
            invalid.append(entry)
            continue
        valid.append(entry)
    return valid, invalid


def _success_product_codes(report: Optional[Dict]) -> Set[int]:
    """从装箱报告中收集 SUCCESS 托盘上的 product_code。"""
    codes: Set[int] = set()
    for pallet in (report or {}).get("pallets") or []:
        if pallet.get("mpm_status") != "SUCCESS":
            continue
        for item in pallet.get("packed_items") or []:
            pc = coerce_product_code(item.get("product_code"))
            if pc is not None:
                codes.add(pc)
    return codes


class WcsPackingService:
    """WCS 接口模式常驻服务：拉取落库 + 读库装箱。"""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        safe_compare: bool = False,
    ):
        from run_packing import build_workflow, load_constraint_config

        self._config_path = Path(config_path) if config_path else None
        self._ds = load_data_source_config(self._config_path)
        self._db_cfg = _load_db_config_from_yaml(self._config_path)
        self._repo = WcsStockRepository(self._db_cfg)
        self._repo_all = WcsStockAllRepository(self._db_cfg)
        self._safe_compare = safe_compare
        self._constraint_config = load_constraint_config(self._config_path)
        self._build_workflow = build_workflow
        self._bms_map: Dict[str, float] = {}
        self._stop = threading.Event()
        # use_real_api 开且接口失败时置位；UI 据此按「停止」处理
        self.stopped_by_api_failure = False
        self._ensure_dirs()
        self._reload_reference_data()

    def _request_stop_like_user(self, reason: str) -> None:
        """真实接口失败：打印标记并停机（等同 UI 点「停止」）。"""
        self.stopped_by_api_failure = True
        print(f"{WCS_STOP_MARKER} {reason}")
        self._stop.set()

    def _handle_fetch_error(self, exc: Exception, context: str) -> bool:
        """处理拉取异常。返回 True 表示应结束当前循环/模式。"""
        if self._ds.use_real_api:
            self._request_stop_like_user(
                f"真实接口调用失败（{context}），服务停止：{exc}"
            )
            return True
        print(f"[WCS-拉] {context}异常（备用 Postman）：{exc}")
        return False

    @property
    def raw_dir(self) -> Path:
        """接口 1 原始响应（input 下唯一保留的数据目录）。"""
        return self._ds.input_dir / "raw"

    @property
    def bad_dir(self) -> Path:
        return self._ds.input_dir / "bad"

    def _ensure_dirs(self) -> None:
        for d in (self._ds.input_dir, self.raw_dir, self.bad_dir, self._ds.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _reload_reference_data(self) -> None:
        bms_path = self._ds.bms_reference_file
        if bms_path.exists():
            self._bms_map = load_bms_map(bms_path)
            print(f"[WCS] 已加载 BMS 参考表：{bms_path}")
        else:
            self._bms_map = {}
            print(f"[WCS] 警告：BMS 参考文件不存在：{bms_path}，指数将按 0 处理。")

    def _make_workflow(self):
        wf = self._build_workflow(
            safe_compare=self._safe_compare,
            constraint_config=self._constraint_config,
        )
        wf._report_persister = NullReportPersister()
        return wf

    # ------------------------------------------------------------------ fetch
    def fetch_once(self) -> int:
        """拉一次接口 1：原始 JSON 落 raw/；库存有变则全量替换并请求本轮装箱。

        返回 1 表示 wcs_stock_box 已变化并已请求装箱；0 表示无变化。
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"\n{'=' * 60}")
        print(f"[WCS-拉] {ts}：拉取接口 1 …")
        stock_body = fetch_stock_response(
            self._ds.effective_api_base_url, self._ds.stock_path
        )

        raw_path = self.raw_dir / f"{ts}.json"
        _save_json(raw_path, stock_body)
        print(f"[WCS-拉] 原始响应已保存：{raw_path}")

        stock_entries = stock_body.get("data") or []
        kept, dropped, dropped_types = _filter_mh423c(stock_entries)
        if dropped:
            print(
                f"[WCS-拉] 已剔除 case_type≠{_SUPPORTED_CASE_TYPE} 的品类 "
                f"{dropped} 条（类型：{dropped_types}），保留 {len(kept)} 条。"
            )
        else:
            print(f"[WCS-拉] 库存品类数：{len(kept)}（均为 {_SUPPORTED_CASE_TYPE}）")

        dimension_candidates = kept
        kept, invalid_dimensions = _split_positive_dimension_entries(
            dimension_candidates
        )
        if invalid_dimensions:
            samples = ", ".join(
                "product_code="
                f"{entry.get('product_code')}/"
                f"box_type={entry.get('box_type')}/"
                f"{entry.get('length')}×{entry.get('width')}×{entry.get('height')}"
                for entry in invalid_dimensions[:5]
            )
            print(
                f"[WCS-拉] 忽略 {len(invalid_dimensions)} 条零尺寸/非法尺寸库存；"
                f"有效记录 {len(kept)} 条；样例：{samples}"
            )

        if dimension_candidates and not kept:
            sync_stats = self._repo.sync_stock_entries(
                kept, allow_empty_replace=True
            )
        else:
            sync_stats = self._repo.sync_stock_entries(kept)
        if sync_stats.unchanged:
            print(
                f"[WCS-拉] wcs_stock_box 与本次立库 product_code 一致"
                f"（候选 {len(kept)}），不替换、不触发装箱。"
            )
        else:
            print(
                f"[WCS-拉] wcs_stock_box 已全量替换："
                f"删 {sync_stats.deleted}，插 {sync_stats.inserted}。"
            )

        all_stats = self._repo_all.insert_new_stock_entries(kept)
        print(
            f"[WCS-拉] wcs_stock_box_all 追加：新插入 {all_stats.inserted}，"
            f"跳过已有 {all_stats.skipped_existing}（历史不删）。"
        )

        if sync_stats.changed:
            print("[WCS-拉] 库存有变化 → 本轮继续装箱。")
            return 1

        print("[WCS-拉] 库存无变化 → 本轮不装箱。")
        return 0

    # ------------------------------------------------------------------ pack
    def pack_once(self) -> PackRunResult:
        """从 DB 读当前表全部箱子装箱（无达标过滤 / 无达标回写）。

        Returns:
            本轮是否计算、成功托盘数与报告路径。
        """
        rows = self._repo.fetch_all_rows()
        if not rows:
            print("[WCS-装] 库中无库存行，跳过。")
            return PackRunResult(executed=False)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"\n{'=' * 60}")
        print(f"[WCS-装] {ts}：库存行 {len(rows)} 条，开始装箱 …")

        stock_entries = self._repo.rows_to_stock_entries(rows)
        pallet_dims = default_pallet_dims_map(self._config_path)
        boxes = stock_to_boxes(stock_entries, self._bms_map, pallet_dims)
        print(f"[WCS-装] 展开为 {len(boxes)} 个箱子。")

        if not boxes:
            print("[WCS-装] 展开后无箱，跳过。")
            return PackRunResult(executed=True)

        try:
            workflow = self._make_workflow()
            report = workflow.run_with_boxes(boxes)
        except Exception as exc:
            print(f"[WCS-装] 装箱异常：{exc}")
            bad_path = self.bad_dir / f"pack_{ts}.json"
            _save_json(bad_path, {"timestamp": ts, "error": str(exc)})
            return PackRunResult(executed=True)

        if report is None:
            print("[WCS-装] 装箱失败（无有效报告）。")
            return PackRunResult(executed=True)

        success_pallets = sum(
            1
            for pallet in (report.get("pallets") or [])
            if str(pallet.get("mpm_status") or "").upper() == "SUCCESS"
        )
        success_codes = _success_product_codes(report)
        failed_pallets = sum(
            1
            for p in (report.get("pallets") or [])
            if p.get("mpm_status") == "FAILED"
        )
        print(
            f"[WCS-装] SUCCESS 产品码 {len(success_codes)} 个，"
            f"SUCCESS 盘 {success_pallets}，FAILED 盘 {failed_pallets}。"
        )
        print("[WCS-装] 本轮计算结束。")

        # 一次计算只写一份完整 JSON（成功+失败托盘都在内）；
        # 有任一达标盘 → success/，否则 → fail/。
        bucket = resolve_report_bucket_dir(self._ds.output_dir, report)
        report_path = bucket / f"packing_plan_{ts}.json"
        _save_json(report_path, report)
        print(f"[WCS-装] 本轮方案已保存（{bucket.name}）：{report_path}")

        has_success = report_has_success_pallets(report)
        execution_outcome = None
        plan = report_to_plan_result(report)
        if has_success:
            try:
                from src.postprocess.execution_planning_hook import (
                    run_execution_planning_for_plan,
                )

                exec_config = self._config_path or DEFAULT_PACKING_CONFIG
                execution_outcome = run_execution_planning_for_plan(
                    report_path,
                    exec_config,
                    output_dir=self._ds.output_dir,
                    log=print,
                )
            except Exception as exc:
                print(f"[执行规划] 调用异常，统一回退原方案：{exc}")

            try:
                plan = select_wcs_plan_result(report, execution_outcome)
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                print(f"[执行规划] 执行文件读取失败，统一回退原方案：{exc}")
                execution_outcome = None
                plan = report_to_plan_result(report)

        execution_used = bool(
            execution_outcome is not None
            and getattr(execution_outcome, "succeeded", False)
        )
        selected_label = "执行顺序方案" if execution_used else "原装箱方案"
        if has_success:
            plan_path = bucket / f"wcs_plan_{ts}.json"
            _save_json(plan_path, plan.cases)
            print(
                f"[WCS-装] 接口 2 使用{selected_label}，发送体已保存："
                f"{plan_path}（{len(plan.cases)} 个 case）"
            )

            map_path = bucket / f"wcs_plan_map_{ts}.json"
            _save_json(
                map_path,
                {uid: pallet for uid, pallet in plan.plan_by_unique_id.items()},
            )
            print(f"[WCS-装] {selected_label}执行层映射已保存：{map_path}")
        else:
            print("[WCS-装] 无达标托盘，跳过 wcs_plan / wcs_plan_map 写入。")

        if _PUSH_PLAN_TO_WCS and plan.cases:
            try:
                push_body = push_plan_result(
                    self._ds.effective_api_base_url,
                    plan.cases,
                    self._ds.plan_path,
                )
                print(
                    f"[WCS-装] 接口 2 推送成功：code={push_body.get('code')}, "
                    f"msg={push_body.get('msg')}"
                )
            except Exception as exc:
                print(f"[WCS-装] 接口 2 推送失败：{exc}")
        elif _PUSH_PLAN_TO_WCS:
            print("[WCS-装] 无达标 case，跳过接口 2 推送。")
        else:
            print("[WCS-装] 已跳过接口 2 推送（仅本地保存）。")

        effective_report_path = (
            execution_outcome.report_path
            if execution_used
            else report_path.resolve()
        )
        print(f"[UI-RESULT] {effective_report_path}")
        return PackRunResult(
            executed=True,
            success_pallets=success_pallets,
            report_path=effective_report_path,
        )

    # ------------------------------------------------------------------ loops
    def _wait_for_next_fetch(self, started_at: float) -> bool:
        """等待到以上次拉取开始时间为基准的下一个周期。"""
        elapsed = max(0.0, time.monotonic() - started_at)
        remaining = max(
            0.0,
            float(self._ds.download_interval) - elapsed,
        )
        return self._stop.wait(remaining)

    def run_loop(self) -> None:
        print("=" * 60)
        print("WCS 接口装箱服务（DB 模式）")
        print(
            f"  接口模式：{'真实 WCS' if self._ds.use_real_api else 'Postman 备用'}"
            f"（use_real_api={self._ds.use_real_api}）"
        )
        print(f"  接口地址：{self._ds.effective_api_base_url}")
        print(f"  接口1：{self._ds.stock_url()}")
        print(f"  接口2：{self._ds.plan_url()}")
        print(f"  拉取间隔：{self._ds.download_interval} 秒（仅拉取）")
        print(f"  原始 JSON：{self.raw_dir}")
        print(
            f"  数据库：{self._db_cfg.host}:{self._db_cfg.port}/"
            f"{self._db_cfg.database} 表 wcs_stock_box（当前）"
            f" / wcs_stock_box_all（历史）"
        )
        print(f"  BMS 参考：{self._ds.bms_reference_file}")
        print(f"  输出目录：{self._ds.output_dir}")
        print(
            "  触发：wcs_stock_box 的 product_code 集合相对立库有变化才全量替换并开算；"
            "拉取与装箱串行；历史表只追加"
        )
        if self._config_path:
            print(f"  约束配置：{self._config_path}")
        print("  按 Ctrl+C 或由 UI 停止按钮结束进程")
        print("=" * 60)

        try:
            while not self._stop.is_set():
                started_at = time.monotonic()
                try:
                    changed = self.fetch_once()
                except Exception as exc:
                    if self._handle_fetch_error(exc, "本轮拉取"):
                        break
                else:
                    if changed > 0:
                        try:
                            self._reload_reference_data()
                            self.pack_once()
                        except Exception as exc:
                            print(f"[WCS-装] 循环异常：{exc}")
                    else:
                        print("[WCS-装] 本轮库存无变化，不装箱。")

                if self._wait_for_next_fetch(started_at):
                    break
        except KeyboardInterrupt:
            print("[WCS] 收到停止信号，正在结束 …")
            self._stop.set()
            print("[WCS] 服务已结束。")

    def run_once(self) -> bool:
        """调试：拉一次 + 若库存有变化则装一次。"""
        try:
            changed = self.fetch_once()
        except Exception as exc:
            if self._handle_fetch_error(exc, "run_once 拉取"):
                return False
            return False
        if changed <= 0:
            print("[WCS] run_once：库存无变化，不装箱。")
            return True
        return self.pack_once().executed

    def run_until_success(self) -> bool:
        """循环拉取并装箱，首轮出现成功托盘后停止。"""
        round_no = 0
        print("[WCS] 运行模式：循环拉取，直到出现成功托盘后停止。")
        while not self._stop.is_set():
            round_no += 1
            started_at = time.monotonic()
            print(f"[WCS] 成功等待模式：第 {round_no} 轮拉取。")
            try:
                changed = self.fetch_once()
                if changed > 0:
                    self._reload_reference_data()
                    outcome = self.pack_once()
                    if outcome.success_pallets > 0:
                        print(
                            "[WCS-UNTIL-SUCCESS] "
                            f"本轮发现 {outcome.success_pallets} 个成功托盘，服务停止。"
                        )
                        return True
                    print("[WCS] 本轮尚无成功托盘，将继续等待新数据。")
                else:
                    print("[WCS] 本轮无新数据，不重复计算现有库存。")
            except Exception as exc:
                if self._handle_fetch_error(exc, "成功等待模式本轮"):
                    return False

            if self._wait_for_next_fetch(started_at):
                break

        print("[WCS] 成功等待模式已停止，尚未产生成功托盘。")
        return False
