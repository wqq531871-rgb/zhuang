"""WCS 接口装箱常驻服务（HTTP 服务壳）。

两条独立流水线（互不等待）：

1. 拉取器：每 download_interval 秒 POST 接口 1；
   原始 JSON → ``input/raw/``（本地仅保留此目录）；
   过滤 MH423C 后按 ``product_code`` 插入 ``zhuangdb.wcs_stock_box``
   （已存在则跳过；新行 ``up_to_standard=0``）。仅当有新插入时唤醒装箱。

2. 装箱器：被新插入唤醒后，读取库中全部未达标行作为算法输入；
   算完把 SUCCESS 盘箱子的 ``up_to_standard`` 更新为 1；未达标保持 0。
   无新插入则暂停，避免未达标箱反复空转。

可选：装箱结果推送接口 2（由 ``_PUSH_PLAN_TO_WCS`` 控制）。
"""

from __future__ import annotations

import json
import threading
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
from src.adapter.wcs_adapter import build_stock_request, coerce_product_code
from src.config import (
    DATA_DIR,
    DEFAULT_PACKING_CONFIG,
    INPUT_DIR,
    OUTPUT_DIR,
    WORKSPACE_ROOT,
    ConfigLoader,
)
from src.main.report_persister import NullReportPersister
from src.service.stock_db import (
    WcsStockRepository,
    load_database_config,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 接口模式下仅处理该托盘型号；其余 case_type 在落库前剔除。
_SUPPORTED_CASE_TYPE = "MH423C"
# False=只本地装箱/落盘，不向接口 2 推送结果（调试用，恢复推送改 True）。
_PUSH_PLAN_TO_WCS = False
# 装箱器空闲等待超时（秒）：防止漏掉 wake 信号。
_PACK_IDLE_POLL_SEC = 2.0

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


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


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
        self._safe_compare = safe_compare
        self._constraint_config = load_constraint_config(self._config_path)
        self._build_workflow = build_workflow
        self._bms_map: Dict[str, float] = {}
        self._stop = threading.Event()
        # 仅有新插入时置位，装箱线程据此开算
        self._db_insert_wake = threading.Event()
        # use_real_api 开且接口失败时置位；UI 据此按「停止」处理
        self.stopped_by_api_failure = False
        self._ensure_dirs()
        self._reload_reference_data()

    def _request_stop_like_user(self, reason: str) -> None:
        """真实接口失败：打印标记并停机（等同 UI 点「停止」）。"""
        self.stopped_by_api_failure = True
        print(f"{WCS_STOP_MARKER} {reason}")
        self._stop.set()
        self._db_insert_wake.set()

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
        """拉一次接口 1：原始 JSON 落 raw/，新箱子插入 DB。返回新插入行数。"""
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

        inserted = self._repo.insert_new_stock_entries(kept)
        print(
            f"[WCS-拉] 落库完成：候选 {len(kept)} 条，新插入 {inserted} 条"
            f"（新行 up_to_standard=0）。"
        )
        if inserted > 0:
            self._db_insert_wake.set()
            print("[WCS-拉] 有新插入 → 唤醒装箱线程。")
        else:
            print("[WCS-拉] 无新插入 → 不触发装箱。")
        return inserted

    # ------------------------------------------------------------------ pack
    def pack_once(self) -> PackRunResult:
        """从 DB 读全部未达标箱子装箱；达标行回写 up_to_standard=1。

        Returns:
            本轮是否计算、成功托盘数与报告路径。
        """
        rows = self._repo.fetch_unmet_rows()
        if not rows:
            print("[WCS-装] 库中无未达标箱子，跳过。")
            return PackRunResult(executed=False)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"\n{'=' * 60}")
        print(f"[WCS-装] {ts}：未达标行 {len(rows)} 条，开始装箱 …")

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
        updated = self._repo.mark_standard_by_product_codes(success_codes)
        failed_pallets = sum(
            1
            for p in (report.get("pallets") or [])
            if p.get("mpm_status") == "FAILED"
        )
        print(
            f"[WCS-装] SUCCESS 产品码 {len(success_codes)} 个，"
            f"DB 更新达标 {updated} 行；FAILED 盘 {failed_pallets} 个保持未达标。"
        )
        print("[WCS-装] 本轮结束；等待下一次「新插入」再开算。")

        report_path = self._ds.output_dir / f"packing_plan_{ts}.json"
        _save_json(report_path, report)
        print(f"[WCS-装] 装箱报告已保存：{report_path}")

        plan = report_to_plan_result(report)
        plan_path = self._ds.output_dir / f"wcs_plan_{ts}.json"
        _save_json(plan_path, plan.cases)
        print(f"[WCS-装] 接口 2 发送体已保存：{plan_path}（{len(plan.cases)} 个 case）")

        if _PUSH_PLAN_TO_WCS:
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
        else:
            print("[WCS-装] 已跳过接口 2 推送（仅本地保存）。")

        map_path = self._ds.output_dir / f"wcs_plan_map_{ts}.json"
        _save_json(
            map_path,
            {uid: pallet for uid, pallet in plan.plan_by_unique_id.items()},
        )
        print(f"[UI-RESULT] {report_path.resolve()}")
        return PackRunResult(
            executed=True,
            success_pallets=success_pallets,
            report_path=report_path.resolve(),
        )

    # ------------------------------------------------------------------ loops
    def _fetch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.fetch_once()
            except Exception as exc:
                if self._handle_fetch_error(exc, "本轮拉取"):
                    break
            if self._stop.wait(self._ds.download_interval):
                break

    def _pack_loop(self) -> None:
        """仅在有新插入时装箱；算完后暂停直到下一次插入。"""
        idle_announced = False
        while not self._stop.is_set():
            # 等待「有新插入」信号
            if not self._db_insert_wake.is_set():
                if not idle_announced:
                    print(
                        "[WCS-装] 等待数据库新插入（有新 product_code 才开算）…"
                    )
                    idle_announced = True
                self._db_insert_wake.wait(timeout=_PACK_IDLE_POLL_SEC)
                if self._stop.is_set():
                    break
                if not self._db_insert_wake.is_set():
                    continue

            idle_announced = False
            self._db_insert_wake.clear()
            try:
                self._reload_reference_data()
                self.pack_once()
            except Exception as exc:
                print(f"[WCS-装] 循环异常：{exc}")
            # 算完不自动连算；若装箱期间又有新插入，wake 会被再次 set，下一圈继续

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
            f"{self._db_cfg.database} 表 wcs_stock_box"
        )
        print(f"  BMS 参考：{self._ds.bms_reference_file}")
        print(f"  输出目录：{self._ds.output_dir}")
        print("  触发：仅「新插入」开算；达标回写 up_to_standard=1")
        if self._config_path:
            print(f"  约束配置：{self._config_path}")
        print("  按 Ctrl+C 或由 UI 停止按钮结束进程")
        print("=" * 60)

        fetch_thread = threading.Thread(
            target=self._fetch_loop, name="wcs-fetch", daemon=True
        )
        pack_thread = threading.Thread(
            target=self._pack_loop, name="wcs-pack", daemon=True
        )
        fetch_thread.start()
        pack_thread.start()
        try:
            while fetch_thread.is_alive() or pack_thread.is_alive():
                fetch_thread.join(timeout=0.5)
                pack_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            print("[WCS] 收到停止信号，正在结束 …")
            self._stop.set()
            self._db_insert_wake.set()
            fetch_thread.join(timeout=5)
            pack_thread.join(timeout=5)
            print("[WCS] 服务已结束。")

    def run_once(self) -> bool:
        """调试：拉一次 + 若有新插入则装一次。"""
        try:
            inserted = self.fetch_once()
        except Exception as exc:
            if self._handle_fetch_error(exc, "run_once 拉取"):
                return False
            return False
        if inserted <= 0:
            print("[WCS] run_once：无新插入，不装箱。")
            return True
        return self.pack_once().executed

    def run_until_success(self) -> bool:
        """循环拉取并装箱，首轮出现成功托盘后停止。"""
        round_no = 0
        print("[WCS] 运行模式：循环拉取，直到出现成功托盘后停止。")
        while not self._stop.is_set():
            round_no += 1
            print(f"[WCS] 成功等待模式：第 {round_no} 轮拉取。")
            try:
                inserted = self.fetch_once()
                if inserted > 0:
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

            if self._stop.wait(self._ds.download_interval):
                break

        print("[WCS] 成功等待模式已停止，尚未产生成功托盘。")
        return False