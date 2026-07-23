# -*- coding: utf-8 -*-
"""
Industrial Packing Workbench V3 Clean

核心目标：
1. 直接选择 Excel，不需要手动修改 packing_config.yaml；
2. 自动复制输入 Excel 到 data/ui_inputs，避免中文路径/空格路径带来的问题；
3. 自动生成 runtime/packing-realtime/temp 下的临时 YAML
4. 后端运行时强制追加 --out，把 JSON 输出到 runtime/packing-realtime/exports；
5. 后端完成后直接加载这个 JSON 到界面，不再让用户手动找 packing_plan_*.json。

推荐运行：
    python ui/realtime_dashboard_v3_clean.py --project .
    或 tools/windows/start_realtime_dashboard_v3_clean.bat

启动仪表盘时会自动后台拉起 local_wcs_receiver（局域网接口 3/4/7）；
关闭窗口时自动停止。配置见 local_wcs_receiver/config/receiver_config.yaml。

可通过顶栏「打开机器人仿真」以独立进程启动同级 packing-robot（PySide6）。

数据目录默认：同级 packing-workspace/（可用 PACKING_WORKSPACE 覆盖）
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

# -----------------------------------------------------------------------------
# Import v2 safely. v2 already contains the Qt plugin path fix and UI theme.
# -----------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
_THIS_DIR = _THIS_FILE.parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise RuntimeError("PyYAML is required. Please: pip install PyYAML") from exc

try:
    import pandas as pd
except Exception as exc:  # pragma: no cover
    raise RuntimeError("pandas/openpyxl are required for Excel sheet detection.") from exc

try:
    from PyQt5 import QtCore, QtWidgets
except Exception as exc:  # pragma: no cover
    raise RuntimeError("PyQt5 is required. Please: pip install PyQt5") from exc

try:
    from dashboard_state import (
        RUN_MODE_OPTIONS,
        apply_download_interval,
        list_success_pallets,
        normalize_download_interval,
        run_mode_policy,
    )
    from runtime_paths import (
        backend_command,
        is_frozen,
        packing_entry_exists,
        receiver_entry_exists,
        wcs_entry_exists,
    )
    from realtime_dashboard_v2 import (
        IndustrialPackingWorkbench,
        StatusPill,
        StepCard,
        DEFAULT_CONFIG_REL,
        DEFAULT_RUN_SCRIPT_REL,
        RUNTIME_NAME,
        _PROJECT_DIR_DEFAULT,
        ensure_runtime_dirs,
        runtime_dir_from_project,
        log_dir_from_project,
        find_latest_json,
        workspace_dir_from_project,
    )
    from robot_ui_launcher import launch_robot_ui
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "Cannot import realtime_dashboard_v2.py. Keep this file in ui/."
    ) from exc

DEFAULT_WCS_RUN_SCRIPT_REL = Path(r"packing\run_wcs_service.py")
LOCAL_WCS_RECEIVER_REL = Path("local_wcs_receiver")
LOCAL_WCS_RECEIVER_SCRIPT = LOCAL_WCS_RECEIVER_REL / "run_receiver.py"
LOCAL_WCS_RECEIVER_CONFIG = LOCAL_WCS_RECEIVER_REL / "config" / "receiver_config.yaml"


def _receiver_advertise_url(project_dir: Path) -> str:
    cfg = Path(project_dir) / LOCAL_WCS_RECEIVER_CONFIG
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return "http://127.0.0.1:8093"
        url = str(data.get("advertise_base_url") or "").strip()
        if url:
            return url.rstrip("/")
        server = data.get("server") or {}
        port = int(server.get("port") or data.get("port") or 8093)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8093"


def _start_local_wcs_receiver(
    project_dir: Path,
    emit_log,
) -> Optional[subprocess.Popen]:
    """随仪表盘后台启动局域网接收端；已在跑则跳过。"""
    project_dir = Path(project_dir).resolve()
    script = project_dir / LOCAL_WCS_RECEIVER_SCRIPT
    config = project_dir / LOCAL_WCS_RECEIVER_CONFIG
    if not receiver_entry_exists(project_dir):
        emit_log(f"[UI] 未找到接收端入口，跳过自动启动：{script}")
        return None
    if not config.exists():
        emit_log(f"[UI] 未找到接收端配置，跳过自动启动：{config}")
        return None

    receiver_root = project_dir / LOCAL_WCS_RECEIVER_REL
    log_dir = receiver_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"receiver_ui_{stamp}.log"
    log_fp = open(log_path, "a", encoding="utf-8", errors="replace")

    if is_frozen():
        cmd = backend_command("receiver", ["--config", str(config)])
        cwd = str(project_dir)
    else:
        cmd = [sys.executable, str(script), "--config", str(config)]
        cwd = str(receiver_root)
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError as exc:
        log_fp.close()
        emit_log(f"[UI] 自动启动局域网接收端失败：{exc}")
        return None

    # 短暂等待：端口被占用时进程会很快退出
    time.sleep(0.8)
    if proc.poll() is not None:
        log_fp.close()
        emit_log(
            f"[UI] 局域网接收端未能保持运行（退出码 {proc.returncode}）。"
            f"请看日志：{log_path}（常见原因：8093 端口已被占用）。"
        )
        return None

    # 进程还活着时保持文件句柄，随进程生命周期由 OS 回收；存到 proc 上便于关闭
    proc._receiver_log_fp = log_fp  # type: ignore[attr-defined]
    advertise = _receiver_advertise_url(project_dir)
    emit_log(f"[UI] 已自动启动局域网接收端（PID {proc.pid}）")
    emit_log(f"[UI] 接收端根地址：{advertise}")
    emit_log(f"[UI] 接收端 Swagger：{advertise}/swagger/index.html")
    emit_log(f"[UI] 接收端日志：{log_path}")
    return proc


def _stop_local_wcs_receiver(proc: Optional[subprocess.Popen], emit_log) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        fp = getattr(proc, "_receiver_log_fp", None)
        if fp:
            try:
                fp.close()
            except Exception:
                pass
        return
    emit_log(f"[UI] 正在停止局域网接收端（PID {proc.pid}）…")
    try:
        if sys.platform.startswith("win"):
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    except Exception as exc:
        emit_log(f"[UI] 停止接收端时异常：{exc}")
    finally:
        fp = getattr(proc, "_receiver_log_fp", None)
        if fp:
            try:
                fp.close()
            except Exception:
                pass
        emit_log("[UI] 局域网接收端已停止。")


REQUIRED_INCREMENTAL_SHEETS = {"最终挑选结果", "新增箱", "包装物料主数据(BMS)"}
BMS_SHEET = "包装物料主数据(BMS)"


def _safe_ascii_stem(name: str, default: str = "input") -> str:
    stem = Path(name).stem
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")
    return cleaned[:80] or default


def _project_data_dir(project_dir: Path) -> Path:
    """Excel / BMS 数据目录：packing-workspace/data。"""
    return workspace_dir_from_project(project_dir) / "data"


def _ui_inputs_dir(project_dir: Path) -> Path:
    return _project_data_dir(project_dir) / "ui_inputs"


def _runtime_temp_dir(project_dir: Path) -> Path:
    return runtime_dir_from_project(project_dir) / "temp"


def _runtime_exports_dir(project_dir: Path) -> Path:
    return runtime_dir_from_project(project_dir) / "exports"


def _relative_to_data(project_dir: Path, path: Path) -> str:
    data_dir = _project_data_dir(project_dir).resolve()
    return Path(path).resolve().relative_to(data_dir).as_posix()


def _copy_excel_to_project_data(project_dir: Path, excel_path: Path) -> Path:
    excel_path = Path(excel_path).resolve()
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file does not exist: {excel_path}")
    out_dir = _ui_inputs_dir(project_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = excel_path.suffix.lower() if excel_path.suffix else ".xlsx"
    safe_stem = _safe_ascii_stem(excel_path.name)
    dst = out_dir / f"{stamp}_{safe_stem}{suffix}"
    shutil.copy2(excel_path, dst)
    return dst


def _read_excel_mode(excel_path: Path) -> Tuple[str, list[str], list[str]]:
    """Return (run_mode, sheet_names, warnings)."""
    excel_path = Path(excel_path)
    excel = pd.ExcelFile(excel_path)
    sheets = list(excel.sheet_names)
    sheet_set = set(sheets)
    warnings = []

    if "新增箱" in sheet_set:
        mode = "incremental"
        missing = sorted(REQUIRED_INCREMENTAL_SHEETS - sheet_set)
        if missing:
            warnings.append("增量模式缺少工作表：" + "、".join(missing))
    else:
        mode = "normal"
        if BMS_SHEET not in sheet_set:
            warnings.append("普通模式建议包含工作表：包装物料主数据(BMS)")
        if len([s for s in sheets if s not in {BMS_SHEET, "说明"}]) == 0:
            warnings.append("没有发现可作为订单数据的工作表。")
    return mode, sheets, warnings


def _load_yaml(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Base config does not exist: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML config: {path}")
    return data


def _write_ui_config(project_dir: Path, base_config_path: Path, excel_copy_path: Path, run_mode: str) -> Path:
    config = _load_yaml(base_config_path)
    rel_source = _relative_to_data(project_dir, excel_copy_path)

    config["run_mode"] = run_mode
    config.setdefault("excel_data", {})
    config.setdefault("incremental", {})

    # 同时写两个字段，保证用户切换 normal / incremental 时不用再次改配置。
    config["excel_data"]["source_file"] = rel_source
    config["incremental"]["source_file"] = rel_source

    temp_dir = _runtime_temp_dir(project_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg_path = temp_dir / f"ui_config_{run_mode}_{stamp}.yaml"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    return cfg_path


def _write_ui_config_api_only(
    project_dir: Path,
    base_config_path: Path,
    download_interval: Optional[int] = None,
) -> Path:
    """从全局 packing_config.yaml 生成接口模式临时配置。

    database / api 地址 / use_real_api 等一律沿用 base，不在 UI 里改；
    仅覆盖本次运行的 download_interval（若传入）。
    """
    config = _load_yaml(base_config_path)
    config["run_mode"] = "normal"
    prev_ds = dict(config.get("data_source") or {})
    prev_ds["mode"] = "api"
    config["data_source"] = prev_ds
    apply_download_interval(
        config,
        prev_ds.get("download_interval", 200)
        if download_interval is None
        else download_interval,
    )
    # database 段必须来自 base；缺失则报错，禁止在 UI 再写一套密码
    if not config.get("database"):
        raise ValueError(
            f"配置缺少 database 段，请在 {base_config_path} 中填写（全局唯一）。"
        )

    temp_dir = _runtime_temp_dir(project_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg_path = temp_dir / f"ui_config_api_{stamp}.yaml"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    return cfg_path


_WCS_STOP_MARKER = "[WCS-STOP]"
_UI_RESULT_RE = re.compile(r"\[UI-RESULT\]\s*(.+)$")
_RESULT_TS_RE = re.compile(r"(\d{8})_(\d{6})")
_HISTORY_LIMIT = 50
_HISTORY_CURRENT_TOKEN = "__current__"


class ResultHistoryEntry(NamedTuple):
    path: Path
    mtime: float
    source: str
    label: str


def _result_search_roots(project_dir: Path) -> List[Path]:
    project_dir = Path(project_dir).resolve()
    workspace_dir = workspace_dir_from_project(project_dir)
    roots = [
        workspace_dir / "output" / "success",
        workspace_dir / "output" / "fail",
        workspace_dir / "output",
        project_dir / "output" / "success",
        project_dir / "output" / "fail",
        project_dir / "output",
        project_dir / "outputs",
        workspace_dir / "runtime" / RUNTIME_NAME / "exports",
    ]
    # de-dupe while preserving order
    seen = set()
    out: List[Path] = []
    for p in roots:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.exists():
            out.append(p)
    return out


def _guess_result_source(path: Path, project_dir: Path) -> str:
    text = str(path.resolve()).replace("\\", "/").lower()
    name = path.name.lower()
    if "ui_packing_plan" in name or "/exports/" in text:
        return "Excel"
    if "/output/success/" in text or text.endswith("/output/success/" + name):
        return "达标"
    if "/success/" in text:
        return "达标"
    if "/output/fail/" in text or "/fail/" in text:
        return "未达标"
    if "/output/" in text or name.startswith("packing_plan_"):
        return "输出"
    return "手动"


def _format_result_timestamp(path: Path) -> str:
    match = _RESULT_TS_RE.search(path.stem)
    if not match:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    d, t = match.groups()
    return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}:{t[4:6]}"


def _read_result_summary(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        overall = (data.get("summary") or {}).get("overall") or {}
        return {
            "total": overall.get("total_pallets"),
            "success": overall.get("success_pallets"),
            "failed": overall.get("failed_pallets"),
            "runtime": data.get("total_runtime_seconds"),
        }
    except Exception:
        return {}


def _build_result_history_label(path: Path, source: str) -> str:
    ts = _format_result_timestamp(path)
    summary = _read_result_summary(path)
    total = summary.get("total")
    success = summary.get("success")
    failed = summary.get("failed")
    runtime = summary.get("runtime")
    if total is not None and success is not None and failed is not None:
        stat = f"{total}盘·达标{success}·未达标{failed}"
    else:
        stat = path.name
    if runtime is not None:
        try:
            stat += f"·{float(runtime):.0f}s"
        except (TypeError, ValueError):
            pass
    return f"{ts} [{source}] {stat}"


def _is_valid_packing_json(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return isinstance(data, dict) and isinstance(data.get("pallets"), list)
    except Exception:
        return False


def list_result_json_files(project_dir: Path, limit: int = _HISTORY_LIMIT) -> List[ResultHistoryEntry]:
    project_dir = Path(project_dir).resolve()
    seen = set()
    entries: List[ResultHistoryEntry] = []
    patterns = ["packing_plan_*.json", "ui_packing_plan_*.json"]
    roots = _result_search_roots(project_dir)
    # 跨目录：若 success/fail 已有同名 *_execution.json，则隐藏 exports 里的基础方案
    execution_stems = set()
    for root in roots:
        for path in root.glob("*_execution.json"):
            if path.is_file() and _is_valid_packing_json(path):
                name = path.name.lower()
                if name.endswith("_execution.json"):
                    execution_stems.add(name[: -len("_execution.json")])

    for root in roots:
        for pattern in patterns:
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                name = path.name.lower()
                stem_l = path.stem.lower()
                # 有 *_execution.json 时隐藏同戳基础 packing_plan（同目录或跨目录）
                if "_execution" not in name and name.endswith(".json"):
                    sibling = path.with_name(f"{path.stem}_execution.json")
                    if sibling.exists() and _is_valid_packing_json(sibling):
                        continue
                    if stem_l in execution_stems:
                        continue
                if not _is_valid_packing_json(path):
                    continue
                seen.add(key)
                source = _guess_result_source(path, project_dir)
                entries.append(
                    ResultHistoryEntry(
                        path=path.resolve(),
                        mtime=path.stat().st_mtime,
                        source=source,
                        label=_build_result_history_label(path, source),
                    )
                )
    entries.sort(key=lambda e: e.mtime, reverse=True)
    return entries[:limit]


def list_packing_plan_files(project_dir: Path, limit: int = _HISTORY_LIMIT) -> List[Path]:
    """下传/选用的整份报告：优先 ``*_execution.json``（list_result 已隐藏同戳旧方案）。"""
    entries = list_result_json_files(project_dir, limit=limit * 2)
    out: List[Path] = []
    for entry in entries:
        name = entry.path.name.lower()
        if "_execution_wcs" in name:
            continue
        if not (
            name.startswith("packing_plan_") or name.startswith("ui_packing_plan_")
        ):
            continue
        out.append(entry.path)
        if len(out) >= limit:
            break
    return out


def _make_out_path(project_dir: Path, prefix: str = "ui_packing_plan") -> Path:
    out_dir = _runtime_exports_dir(project_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"{prefix}_{stamp}.json"


class UiPackingWorker(QtCore.QThread):
    """Run either one Excel calculation or a selected WCS service mode."""

    log = QtCore.pyqtSignal(str)
    started_cmd = QtCore.pyqtSignal(str)
    finished_json = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        project_dir: Path,
        config_path: Path,
        out_path: Optional[Path] = None,
        run_mode: str = "excel",
        download_interval: int = 200,
        parent=None,
    ):
        super().__init__(parent)
        self.project_dir = Path(project_dir).resolve()
        self.config_path = Path(config_path).resolve()
        self.out_path = Path(out_path).resolve() if out_path else None
        self.run_mode = run_mode
        self.download_interval = normalize_download_interval(download_interval)
        self.process: Optional[subprocess.Popen] = None
        self._stop_requested = False
        self._api_forced_stop = False
        self.completed_ok = False
        self._emitted_results: set[str] = set()
        ensure_runtime_dirs(self.project_dir)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = log_dir_from_project(self.project_dir) / f"backend_{stamp}.log"

    def stop(self) -> None:
        self._stop_requested = True
        if self.process and self.process.poll() is None:
            try:
                if os.name == "nt":
                    self.process.terminate()
                else:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

    @property
    def stopped_like_user(self) -> bool:
        return self._stop_requested or self._api_forced_stop

    def _write_backend_log(self, text: str) -> None:
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def _emit_log(self, text: str) -> None:
        self.log.emit(text)
        self._write_backend_log(text)

    def _maybe_emit_ui_result(self, line: str) -> None:
        match = _UI_RESULT_RE.search(line)
        if not match:
            return
        path = Path(match.group(1).strip().strip('"'))
        if path.exists() and _is_valid_packing_json(path):
            key = str(path.resolve())
            if key not in self._emitted_results:
                self._emitted_results.add(key)
                self.finished_json.emit(key)

    def _spawn_process(self, cmd: list) -> subprocess.Popen:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        creationflags = 0
        preexec_fn = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            preexec_fn = os.setsid
        return subprocess.Popen(
            cmd,
            cwd=str(self.project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
            preexec_fn=preexec_fn,
        )

    def _run_manual_mode(self, run_script: Path) -> None:
        assert self.out_path is not None
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        if self.out_path.exists():
            try:
                self.out_path.unlink()
            except Exception:
                pass

        if is_frozen():
            cmd = backend_command(
                "packing",
                [
                    "--config",
                    str(self.config_path),
                    "--out",
                    str(self.out_path),
                ],
            )
        else:
            cmd = [
                sys.executable,
                str(run_script),
                "--config",
                str(self.config_path),
                "--out",
                str(self.out_path),
            ]
        cmd_text = " ".join(f'"{x}"' if " " in x else x for x in cmd)
        self.started_cmd.emit(cmd_text)
        self._emit_log(f"[LOG] 后端日志文件：{self.log_file}")
        self._emit_log(f"[LOG] 本次结果将输出到：{self.out_path}")
        self._write_backend_log(f"[CMD] {cmd_text}")

        self.process = self._spawn_process(cmd)
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if self._stop_requested:
                self._emit_log("[UI] 已请求停止后端装箱。")
                return
            msg = line.rstrip()
            if msg:
                self._emit_log(msg)

        code = self.process.wait()
        if self._stop_requested:
            self._emit_log("[UI] 后端装箱已停止。")
            return
        if code != 0:
            self.failed.emit(f"装箱算法运行失败，退出码：{code}")
            return

        time.sleep(0.3)
        result_path: Optional[Path] = None
        if self.out_path.exists() and _is_valid_packing_json(self.out_path):
            result_path = self.out_path
        else:
            latest = find_latest_json(self.project_dir)
            if latest and _is_valid_packing_json(latest):
                self._emit_log(f"[提醒] 指定输出未生成，改用搜索到的最新结果：{latest}")
                result_path = latest

        if result_path is not None:
            load_path = self._run_execution_planning(result_path)
            self.finished_json.emit(str(load_path))
            return

        if self.out_path.exists():
            self.failed.emit(
                f"后端已结束，但指定输出不是有效装箱 JSON：{self.out_path}。"
                "需要根节点包含 pallets 列表。"
            )
        else:
            self.failed.emit(
                f"后端已结束，但没有生成指定输出 JSON：{self.out_path}。"
                "请查看底部日志中的后端错误信息。"
            )

    def _run_execution_planning(self, plan_path: Path) -> Path:
        """一键装箱成功后自动跑执行顺序规划；成功则返回 execution JSON 路径供可视化加载。"""
        try:
            packing_root = self.project_dir / "packing"
            packing_root_s = str(packing_root.resolve())
            if packing_root.exists() and packing_root_s not in sys.path:
                sys.path.insert(0, packing_root_s)
            from src.postprocess.execution_planning_hook import (  # type: ignore
                run_execution_planning_for_plan,
            )
            from realtime_dashboard_v2 import workspace_dir_from_project

            outcome = run_execution_planning_for_plan(
                plan_path,
                self.config_path,
                project_root=self.project_dir,
                output_dir=workspace_dir_from_project(self.project_dir) / "output",
                log=self._emit_log,
            )
            if outcome.succeeded:
                self._emit_log(f"[UI] 可视化将加载执行方案：{outcome.report_path}")
                return Path(outcome.report_path)
            self._emit_log("[UI] 执行规划未成功，可视化仍加载原装箱方案。")
        except Exception as exc:
            self._emit_log(f"[执行规划] 调用异常（不影响本轮装箱结果）：{exc}")
        return plan_path

    def _run_api_mode(self, run_script: Path) -> None:
        wcs_script = self.project_dir / DEFAULT_WCS_RUN_SCRIPT_REL
        if not wcs_entry_exists(self.project_dir):
            self.failed.emit(f"找不到 WCS 接口服务入口：{wcs_script}")
            return
        if is_frozen():
            cmd = backend_command(
                "wcs",
                [
                    "--config",
                    str(self.config_path),
                    "--run-mode",
                    self.run_mode,
                ],
            )
        else:
            cmd = [
                sys.executable,
                str(wcs_script),
                "--config",
                str(self.config_path),
                "--run-mode",
                self.run_mode,
            ]
        cmd_text = " ".join(f'"{x}"' if " " in x else x for x in cmd)
        self.started_cmd.emit(cmd_text)
        self._emit_log(f"[LOG] 后端日志文件：{self.log_file}")
        mode_messages = {
            "continuous": f"每 {self.download_interval} 秒拉取并计算，直到手动停止",
            "once": "拉取并计算一次后停止",
            "until-success": (
                f"每 {self.download_interval} 秒拉取并计算，出现成功托盘后自动停止"
            ),
        }
        self._emit_log(f"[LOG] 接口模式：{mode_messages[self.run_mode]}。")
        self._write_backend_log(f"[CMD] {cmd_text}")

        self.process = self._spawn_process(cmd)
        line_queue: queue.Queue = queue.Queue()

        def _reader():
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                line_queue.put(line)

        threading.Thread(target=_reader, daemon=True).start()

        while True:
            if self._stop_requested:
                self._emit_log("[UI] 已请求停止接口装箱服务。")
                return

            try:
                line = line_queue.get(timeout=0.5)
            except queue.Empty:
                if self.process.poll() is not None:
                    break
                continue

            msg = line.rstrip()
            if msg:
                self._emit_log(msg)
                self._maybe_emit_ui_result(msg)
                if _WCS_STOP_MARKER in msg:
                    self._api_forced_stop = True

            if self.process.poll() is not None and line_queue.empty():
                break

        code = self.process.wait()
        if self.stopped_like_user:
            self._emit_log("[UI] 接口装箱服务已停止。")
            return
        if code != 0:
            self.failed.emit(f"接口装箱服务异常退出，退出码：{code}")
            return
        self.completed_ok = True

    def run(self) -> None:
        try:
            run_script = self.project_dir / DEFAULT_RUN_SCRIPT_REL
            if not packing_entry_exists(self.project_dir):
                self.failed.emit(f"找不到装箱算法入口：{run_script}")
                return
            if not self.config_path.exists():
                self.failed.emit(f"找不到配置文件：{self.config_path}")
                return

            if self.run_mode != "excel":
                self._run_api_mode(run_script)
            else:
                self._run_manual_mode(run_script)
        except Exception as exc:
            self.failed.emit(str(exc))


class IndustrialPackingWorkbenchClean(IndustrialPackingWorkbench):
    """V3 UI: direct Excel selection + guaranteed output JSON autoload."""

    def __init__(self, project_dir: Path):
        self.selected_excel_original: Optional[Path] = None
        self.selected_excel_copy: Optional[Path] = None
        self.generated_config_path: Optional[Path] = None
        self.generated_out_path: Optional[Path] = None
        self.last_excel_mode: Optional[str] = None
        self.run_mode = "continuous"
        self._active_run_mode: Optional[str] = None
        self._api_service_active = False
        self._history_refreshing = False
        self._current_result_path: Optional[Path] = None
        self._live_result_path: Optional[Path] = None
        try:
            base_config = _load_yaml(Path(project_dir) / DEFAULT_CONFIG_REL)
            ds = base_config.get("data_source") or {}
            configured_interval = ds.get("download_interval", 200)
        except (OSError, ValueError, TypeError):
            configured_interval = 200
        self.download_interval = normalize_download_interval(configured_interval)
        self._local_wcs_receiver_proc: Optional[subprocess.Popen] = None
        self._robot_ui_process: Optional[subprocess.Popen] = None
        super().__init__(project_dir)
        self.setWindowTitle("面向控序混码场景智能装箱规划系统 V3 - 一键装箱 + 结果分析")
        self._write_log("[UI] V3模式：主流程为 选择Excel → 一键装箱；高级算法操作已合并到“算法设置”。")
        self.refresh_result_history()
        self._local_wcs_receiver_proc = _start_local_wcs_receiver(
            self.project_dir, self._write_log
        )

    # ------------------------------------------------------------------ header
    def _build_header(self) -> QtWidgets.QWidget:
        """Top bar: keep the main workflow obvious and move advanced algorithm actions into one menu."""
        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)

        title_box = QtWidgets.QVBoxLayout()
        self.title_label = QtWidgets.QLabel("面向控序混码场景智能装箱规划系统")
        self.title_label.setObjectName("MainTitle")
        self.subtitle_label = QtWidgets.QLabel("一键装箱 · 结果分析 · 托盘切换 · 稳定性评估")
        self.subtitle_label.setObjectName("MainSubtitle")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        layout.addLayout(title_box, 1)

        self.status_pill = StatusPill("空闲")
        self.status_pill.setToolTip("当前运行状态：空闲 / 运行中 / 已完成 / 失败")
        layout.addWidget(self.status_pill)

        self.lbl_run_mode = QtWidgets.QLabel("运行方式")
        layout.addWidget(self.lbl_run_mode)

        self.cmb_run_mode = QtWidgets.QComboBox()
        self.cmb_run_mode.setMinimumWidth(140)
        self.cmb_run_mode.setToolTip("选择接口持续/单次/成功即停，或 Excel 单次运行")
        for label, mode in RUN_MODE_OPTIONS:
            self.cmb_run_mode.addItem(label, mode)
        self.cmb_run_mode.currentIndexChanged.connect(self._on_run_mode_changed)
        layout.addWidget(self.cmb_run_mode)

        self.lbl_download_interval = QtWidgets.QLabel("拉取间隔")
        self.lbl_download_interval.setToolTip("WCS 接口库存数据的拉取周期")
        layout.addWidget(self.lbl_download_interval)

        self.sp_download_interval = QtWidgets.QSpinBox()
        self.sp_download_interval.setRange(1, 86400)
        self.sp_download_interval.setValue(self.download_interval)
        self.sp_download_interval.setSuffix(" 秒")
        self.sp_download_interval.setToolTip("允许范围：1–86400 秒")
        self.sp_download_interval.valueChanged.connect(
            lambda value: setattr(self, "download_interval", int(value))
        )
        layout.addWidget(self.sp_download_interval)

        self.btn_excel = QtWidgets.QPushButton("选择Excel")
        self.btn_excel.setObjectName("GhostButton")
        self.btn_excel.setToolTip("选择装箱输入 Excel，并自动生成本次运行配置。")
        self.btn_excel.clicked.connect(self.choose_excel_file)
        layout.addWidget(self.btn_excel)

        self.btn_excel_run = QtWidgets.QPushButton("一键装箱")
        self.btn_excel_run.setObjectName("PrimaryButton")
        self.btn_excel_run.setToolTip(
            "接口模式：按设置的拉取间隔启动常驻服务。\n"
            "Excel 模式：使用已选择的 Excel 运行一次装箱。"
        )
        self.btn_excel_run.clicked.connect(self.start_excel_packing)
        layout.addWidget(self.btn_excel_run)

        self.btn_algo_settings = QtWidgets.QPushButton("算法设置")
        self.btn_algo_settings.setObjectName("GhostButton")
        self.btn_algo_settings.setToolTip("高级功能：切换算法目录、配置文件，或按当前配置复跑算法。日常使用通常不用点。")
        algo_menu = QtWidgets.QMenu(self.btn_algo_settings)
        self.action_choose_project = algo_menu.addAction("选择算法目录…")
        self.action_choose_project.triggered.connect(self.choose_project_dir)
        self.action_choose_config = algo_menu.addAction("选择配置文件…")
        self.action_choose_config.triggered.connect(self.choose_config_file)
        algo_menu.addSeparator()
        self.action_show_algo_settings = algo_menu.addAction("查看当前设置")
        self.action_show_algo_settings.triggered.connect(self.show_algorithm_settings_info)
        self.action_rerun_config = algo_menu.addAction("按当前配置复跑算法")
        self.action_rerun_config.triggered.connect(self.start_backend_packing)
        self.btn_algo_settings.setMenu(algo_menu)
        layout.addWidget(self.btn_algo_settings)

        # 顶部不再显示“开始装箱”，避免和“一键装箱”混淆。
        # 仍保留一个隐藏按钮属性，兼容父类 on_worker_finished/start_backend_packing 里的启停逻辑。
        self.btn_start_backend = QtWidgets.QPushButton("按配置复跑")
        self.btn_start_backend.setObjectName("GhostButton")
        self.btn_start_backend.setToolTip("高级功能：按当前配置文件直接复跑后端算法。")
        self.btn_start_backend.clicked.connect(self.start_backend_packing)
        self.btn_start_backend.setVisible(False)

        self.btn_stop_backend = QtWidgets.QPushButton("停止")
        self.btn_stop_backend.setObjectName("DangerButton")
        self.btn_stop_backend.setToolTip("停止正在运行的后端算法。")
        self.btn_stop_backend.clicked.connect(self.stop_backend_packing)
        self.btn_stop_backend.setEnabled(False)
        layout.addWidget(self.btn_stop_backend)

        self.btn_load_result = QtWidgets.QPushButton("打开结果文件")
        self.btn_load_result.setObjectName("GhostButton")
        self.btn_load_result.setToolTip("手动选择一个 JSON 装箱结果文件并加载显示。")
        self.btn_load_result.clicked.connect(self.load_json_dialog)
        layout.addWidget(self.btn_load_result)

        self.btn_open_robot = QtWidgets.QPushButton("打开机器人仿真")
        self.btn_open_robot.setObjectName("GhostButton")
        self.btn_open_robot.setToolTip(
            "以独立进程打开 packing-robot 三维仿真界面（PySide6）。\n"
            "已运行时重复点击不会启动第二个实例。"
        )
        self.btn_open_robot.clicked.connect(self.open_robot_ui)
        layout.addWidget(self.btn_open_robot)

        self.cmb_result_history = QtWidgets.QComboBox()
        self.cmb_result_history.setObjectName("GhostCombo")
        self.cmb_result_history.setMinimumWidth(300)
        self.cmb_result_history.setMaximumWidth(420)
        self.cmb_result_history.setToolTip("「当前」= 最新一次装箱结果；其余为历史记录（最近 50 条）")
        self.cmb_result_history.currentIndexChanged.connect(self.on_result_history_changed)
        layout.addWidget(self.cmb_result_history)

        # 兼容父类/旧逻辑；实际入口已合并到历史结果下拉框。
        self.btn_show_latest = QtWidgets.QPushButton("打开最新结果")
        self.btn_show_latest.clicked.connect(self.open_latest_result)
        self.btn_show_latest.setVisible(False)

        self._apply_run_mode_controls()

        return header

    def _build_left_workflow(self) -> QtWidgets.QWidget:
        panel = super()._build_left_workflow()
        layout = panel.layout()
        insert_at = (
            layout.indexOf(self.step_params)
            if hasattr(self, "step_params")
            else layout.count()
        )

        self.step_push = StepCard("↓", "下传 WCS", "选择达标托盘，单盘推送接口2")
        layout.insertWidget(insert_at, self.step_push)

        push_box = QtWidgets.QFrame()
        push_box.setObjectName("ParamBox")
        push_form = QtWidgets.QFormLayout(push_box)
        push_form.setContentsMargins(12, 10, 12, 10)
        push_form.setSpacing(8)

        self.cmb_push_pallet = QtWidgets.QComboBox()
        self.cmb_push_pallet.setMinimumWidth(180)
        self.cmb_push_pallet.setToolTip("当前结果中 mpm_status=SUCCESS 的托盘编号")
        push_form.addRow("达标托盘", self.cmb_push_pallet)

        self.btn_push_wcs = QtWidgets.QPushButton("下传")
        self.btn_push_wcs.setObjectName("PrimaryButton")
        self.btn_push_wcs.setToolTip(
            "从当前 *_execution_wcs.json 读取该盘 case（执行顺序），确认后 POST 接口2"
        )
        self.btn_push_wcs.clicked.connect(self.push_selected_pallet_to_wcs)
        push_form.addRow("", self.btn_push_wcs)

        self.lbl_push_hint = QtWidgets.QLabel("暂无达标托盘可下传")
        self.lbl_push_hint.setObjectName("SmallInfo")
        self.lbl_push_hint.setWordWrap(True)
        push_form.addRow("", self.lbl_push_hint)

        layout.insertWidget(insert_at + 1, push_box)

        self.step_push_plan = StepCard("↓", "下传完整方案", "选 *_execution.json，POST 接口 internal")
        layout.insertWidget(insert_at + 2, self.step_push_plan)

        plan_box = QtWidgets.QFrame()
        plan_box.setObjectName("ParamBox")
        plan_form = QtWidgets.QFormLayout(plan_box)
        plan_form.setContentsMargins(12, 10, 12, 10)
        plan_form.setSpacing(8)

        self.cmb_push_plan = QtWidgets.QComboBox()
        self.cmb_push_plan.setMinimumWidth(220)
        self.cmb_push_plan.setToolTip("优先选 *_execution.json（执行顺序方案）")
        plan_form.addRow("方案 JSON", self.cmb_push_plan)

        self.btn_push_plan = QtWidgets.QPushButton("确定下传")
        self.btn_push_plan.setObjectName("PrimaryButton")
        self.btn_push_plan.setToolTip(
            "将整份执行方案 JSON POST 到 /adaptor/api/wcs/internal"
        )
        self.btn_push_plan.clicked.connect(self.push_selected_plan_internal)
        plan_form.addRow("", self.btn_push_plan)

        self.lbl_push_plan_hint = QtWidgets.QLabel("暂无可下传的执行方案")
        self.lbl_push_plan_hint.setObjectName("SmallInfo")
        self.lbl_push_plan_hint.setWordWrap(True)
        plan_form.addRow("", self.lbl_push_plan_hint)

        layout.insertWidget(insert_at + 3, plan_box)
        self._refresh_push_pallet_combo()
        self._refresh_push_plan_combo()
        return panel

    def _ensure_packing_import_path(self) -> Path:
        packing_root = Path(self.project_dir).resolve() / "packing"
        root_s = str(packing_root)
        if root_s not in sys.path:
            sys.path.insert(0, root_s)
        return packing_root

    def _refresh_push_pallet_combo(self) -> None:
        if not hasattr(self, "cmb_push_pallet"):
            return
        success = list_success_pallets(getattr(self, "pallets", []) or [])
        combo = self.cmb_push_pallet
        prev = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for pallet in success:
            pid = str(pallet.get("pallet_id") or "").strip()
            combo.addItem(pid, pid)
        combo.blockSignals(False)
        if prev:
            idx = combo.findData(prev)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        has_items = combo.count() > 0
        combo.setEnabled(has_items)
        if hasattr(self, "btn_push_wcs"):
            self.btn_push_wcs.setEnabled(has_items)
        if hasattr(self, "lbl_push_hint"):
            self.lbl_push_hint.setText(
                f"可下传 {combo.count()} 个达标托盘（每次仅推送 1 盘）"
                if has_items
                else "暂无达标托盘可下传"
            )
        if hasattr(self, "step_push"):
            detail = (
                f"已加载 {combo.count()} 个达标托盘"
                if has_items
                else "等待装箱结果中的达标托盘"
            )
            self.step_push.set_state("done" if has_items else "idle", detail)

    def populate_after_load(self) -> None:
        super().populate_after_load()
        self._refresh_push_pallet_combo()
        self._refresh_push_plan_combo()

    def _resolve_current_plan_path(self) -> Optional[Path]:
        for candidate in (
            getattr(self, "_live_result_path", None),
            getattr(self, "_current_result_path", None),
            getattr(self, "generated_out_path", None),
        ):
            if candidate is None:
                continue
            path = Path(candidate)
            if path.exists() and _is_valid_packing_json(path):
                return path.resolve()
        return None

    def _refresh_push_plan_combo(self) -> None:
        if not hasattr(self, "cmb_push_plan"):
            return
        combo = self.cmb_push_plan
        prev = combo.currentData()
        plans = list_packing_plan_files(self.project_dir)
        current = self._resolve_current_plan_path()

        combo.blockSignals(True)
        combo.clear()
        if current is not None:
            combo.addItem(f"当前 · {current.name}", str(current))
        for path in plans:
            if current is not None and path.resolve() == current:
                continue
            combo.addItem(path.name, str(path))
        combo.blockSignals(False)

        if prev:
            idx = combo.findData(prev)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        has_items = combo.count() > 0
        combo.setEnabled(has_items)
        if hasattr(self, "btn_push_plan"):
            self.btn_push_plan.setEnabled(has_items)
        if hasattr(self, "lbl_push_plan_hint"):
            self.lbl_push_plan_hint.setText(
                f"可选 {combo.count()} 个方案文件（优先 *_execution.json）"
                if has_items
                else "暂无可下传的执行方案"
            )
        if hasattr(self, "step_push_plan"):
            self.step_push_plan.set_state(
                "done" if has_items else "idle",
                f"已找到 {combo.count()} 个方案" if has_items else "等待执行方案结果",
            )

    def push_selected_plan_internal(self) -> None:
        """确认后，将整份执行方案 JSON POST 到 /adaptor/api/wcs/internal。"""
        if not hasattr(self, "cmb_push_plan") or self.cmb_push_plan.count() == 0:
            QtWidgets.QMessageBox.information(self, "下传完整方案", "没有可下传的方案文件。")
            return
        raw = self.cmb_push_plan.currentData()
        if not raw:
            QtWidgets.QMessageBox.warning(self, "下传完整方案", "请先选择方案 JSON。")
            return
        plan_path = Path(str(raw))
        if not plan_path.exists():
            QtWidgets.QMessageBox.warning(self, "下传完整方案", f"文件不存在：{plan_path}")
            return
        if not _is_valid_packing_json(plan_path):
            QtWidgets.QMessageBox.warning(
                self, "下传完整方案", f"不是有效装箱报告：{plan_path.name}"
            )
            return

        try:
            from result_sequence_update import resolve_execution_report_path

            plan_path = resolve_execution_report_path(plan_path)
            self._ensure_packing_import_path()
            from src.service.wcs_service import (
                load_data_source_config,
                push_internal_plan,
            )

            with open(plan_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            config_path = Path(self.project_dir) / DEFAULT_CONFIG_REL
            ds = load_data_source_config(config_path)
            url = ds.internal_url()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "下传失败", f"读取配置/方案失败：{exc}")
            return

        confirm = QtWidgets.QMessageBox.question(
            self,
            "确认下传完整方案",
            f"确认将该 JSON 整份 POST 到对方接收端？\n\n"
            f"文件：{plan_path.name}\n"
            f"目标：{url}\n\n"
            f"（优先使用 *_execution.json；目标来自 packing_config.yaml → internal_base_url）",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        try:
            self._write_log(f"[UI-完整方案] {plan_path.name} → {url}")
            body = push_internal_plan(
                ds.effective_internal_base_url(),
                payload,
                ds.internal_path,
                raw_json_path=plan_path,
            )
            msg = (
                f"完整方案下传成功。\n文件：{plan_path.name}\n"
                f"目标：{url}\n"
                f"接口返回 code={body.get('code')}, msg={body.get('msg')}"
            )
            self._write_log(f"[UI-完整方案] {msg.replace(chr(10), ' ')}")
            if hasattr(self, "step_push_plan"):
                self.step_push_plan.set_state("done", f"已下传 {plan_path.name}")
            QtWidgets.QMessageBox.information(self, "下传成功", msg)
        except Exception as exc:
            err = f"完整方案下传失败：{exc}"
            self._write_log(f"[UI-完整方案] {err}")
            if hasattr(self, "step_push_plan"):
                self.step_push_plan.set_state("error", "下传失败，请查看日志")
            QtWidgets.QMessageBox.critical(self, "下传失败", err)

    def push_selected_pallet_to_wcs(self) -> None:
        """确认后，将单个达标托盘 POST 到接口 2。"""
        if not hasattr(self, "cmb_push_pallet") or self.cmb_push_pallet.count() == 0:
            QtWidgets.QMessageBox.information(self, "下传", "当前没有可下传的达标托盘。")
            return
        pallet_id = str(self.cmb_push_pallet.currentData() or "").strip()
        if not pallet_id:
            QtWidgets.QMessageBox.warning(self, "下传", "请先选择托盘编号。")
            return
        pallet = next(
            (
                p
                for p in (getattr(self, "pallets", []) or [])
                if str(p.get("pallet_id") or "").strip() == pallet_id
            ),
            None,
        )
        if pallet is None:
            QtWidgets.QMessageBox.warning(self, "下传", f"未找到托盘：{pallet_id}")
            return

        confirm = QtWidgets.QMessageBox.question(
            self,
            "确认下传",
            f"确认是否下传该托盘到 WCS 接口2？\n\n托盘编号：{pallet_id}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        try:
            self._ensure_packing_import_path()
            from result_sequence_update import load_execution_wcs_case_for_pallet
            from src.service.wcs_service import (
                load_data_source_config,
                push_plan_result,
            )

            plan_path = self._resolve_current_plan_path()
            if plan_path is None:
                raise ValueError("当前没有已加载的装箱/执行结果文件")
            case = load_execution_wcs_case_for_pallet(
                plan_path, pallet, box_index=1
            )
            payload = [case]
            config_path = Path(self.project_dir) / DEFAULT_CONFIG_REL
            ds = load_data_source_config(config_path)
            url = ds.plan_url()

            # 本地留存本次单盘下传体，便于核对
            out_dir = workspace_dir_from_project(self.project_dir) / "output" / "success"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", pallet_id)
            save_path = out_dir / f"wcs_push_single_{safe_name}_{stamp}.json"
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            self._write_log(
                f"[UI-下传] 托盘 {pallet_id} 使用执行 WCS："
                f"box_unique_id={case.get('box_unique_id')} ← {plan_path.name}"
            )
            self._write_log(f"[UI-下传] 托盘 {pallet_id} → {url}")
            self._write_log(f"[UI-下传] 请求体已保存：{save_path}")
            body = push_plan_result(
                ds.effective_api_base_url, payload, ds.plan_path
            )
            msg = (
                f"下传成功。\n托盘编号：{pallet_id}\n"
                f"接口返回 code={body.get('code')}, msg={body.get('msg')}"
            )
            self._write_log(f"[UI-下传] {msg.replace(chr(10), ' ')}")
            if hasattr(self, "step_push"):
                self.step_push.set_state("done", f"已下传 {pallet_id}")
            QtWidgets.QMessageBox.information(self, "下传成功", msg)
        except Exception as exc:
            err = f"下传失败：{exc}"
            self._write_log(f"[UI-下传] {err}")
            if hasattr(self, "step_push"):
                self.step_push.set_state("error", "下传失败，请查看日志")
            QtWidgets.QMessageBox.critical(self, "下传失败", err)

    def _current_run_mode(self) -> str:
        if hasattr(self, "cmb_run_mode"):
            mode = self.cmb_run_mode.currentData()
            if mode:
                return str(mode)
        return self.run_mode

    def _on_run_mode_changed(self) -> None:
        self.run_mode = self._current_run_mode()
        self._apply_run_mode_controls()

    def _apply_run_mode_controls(self) -> None:
        policy = run_mode_policy(self._current_run_mode())
        worker_running = bool(self.worker and self.worker.isRunning())
        if hasattr(self, "sp_download_interval"):
            self.sp_download_interval.setEnabled(
                policy.uses_interval and not worker_running
            )
        if hasattr(self, "lbl_download_interval"):
            self.lbl_download_interval.setEnabled(policy.uses_interval)
        if hasattr(self, "btn_excel"):
            self.btn_excel.setEnabled(policy.uses_excel and not worker_running)

    def _write_log(self, text: str) -> None:
        """界面日志与 VSCode 终端同步输出，便于开发调试。"""
        msg = str(text)
        if msg:
            print(msg, flush=True)
        super()._write_log(msg)

    def _current_history_label(self) -> str:
        if self._live_result_path and self._live_result_path.exists():
            detail = _build_result_history_label(
                self._live_result_path,
                _guess_result_source(self._live_result_path, self.project_dir),
            )
            return f"当前 · {detail}"
        return "当前（尚无结果）"

    def refresh_result_history(
        self,
        select_path: Optional[Path] = None,
        select_latest: bool = False,
        select_current: bool = False,
    ) -> None:
        if not hasattr(self, "cmb_result_history"):
            return
        self._history_refreshing = True
        try:
            entries = list_result_json_files(self.project_dir)
            combo = self.cmb_result_history
            combo.blockSignals(True)
            combo.clear()

            combo.addItem(self._current_history_label(), _HISTORY_CURRENT_TOKEN)
            live_resolved = (
                self._live_result_path.resolve()
                if self._live_result_path and self._live_result_path.exists()
                else None
            )

            if not entries and live_resolved is None:
                combo.setCurrentIndex(0)
                combo.setEnabled(True)
                combo.blockSignals(False)
                return

            combo.setEnabled(True)
            select_idx = 0
            target = Path(select_path).resolve() if select_path else None

            for entry in entries:
                if live_resolved is not None and entry.path == live_resolved:
                    continue
                combo.addItem(entry.label, str(entry.path))

            if select_current or select_latest or (
                target is not None and live_resolved is not None and target == live_resolved
            ):
                select_idx = 0
            elif target is not None:
                for idx in range(combo.count()):
                    data = combo.itemData(idx)
                    if data and data != _HISTORY_CURRENT_TOKEN and Path(str(data)) == target:
                        select_idx = idx
                        break

            combo.setCurrentIndex(select_idx)
            combo.blockSignals(False)
        finally:
            self._history_refreshing = False
            self._refresh_push_plan_combo()

    def on_result_history_changed(self, index: int) -> None:
        if self._history_refreshing or index < 0:
            return
        if not hasattr(self, "cmb_result_history"):
            return
        raw = self.cmb_result_history.itemData(index)
        if raw == _HISTORY_CURRENT_TOKEN:
            if not self._live_result_path or not self._live_result_path.exists():
                return
            path = self._live_result_path.resolve()
        elif raw:
            path = Path(str(raw)).resolve()
        else:
            return

        if self._current_result_path and path == self._current_result_path.resolve():
            return
        try:
            label = "当前结果" if raw == _HISTORY_CURRENT_TOKEN else "历史结果"
            self._write_log(f"[UI] 切换{label}：{path}")
            self.load_json_file(path)
            self.show_final_result()
            self._current_result_path = path
            if hasattr(self, "file_info"):
                self.file_info.setText(f"当前结果：{path.name}")
            if hasattr(self, "step_result"):
                self.step_result.set_state("done", f"{label}：{path.name}")
            self.workspace_tabs.setCurrentIndex(0)
        except Exception as exc:
            self.on_backend_failed(f"加载结果失败：{exc}")

    def open_latest_result(self) -> None:
        latest = find_latest_json(self.project_dir)
        if latest is None:
            QtWidgets.QMessageBox.warning(self, "没有找到结果", "没有找到历史装箱 JSON 输出。")
            return
        self.refresh_result_history(select_path=latest, select_current=False)
        self.on_result_history_changed(self.cmb_result_history.currentIndex())

    def open_robot_ui(self) -> None:
        """Open packing-robot as a separate process (same pattern as robot→PLC)."""
        process = getattr(self, "_robot_ui_process", None)
        if process is not None:
            try:
                if process.poll() is None:
                    self._write_log("[UI] 机器人仿真界面已在运行，不重复启动。")
                    QtWidgets.QMessageBox.information(
                        self, "机器人仿真", "机器人仿真界面已经在运行。"
                    )
                    return
            except Exception:
                self._robot_ui_process = None
        try:
            self._robot_ui_process = launch_robot_ui()
        except (OSError, FileNotFoundError) as exc:
            self._write_log(f"[UI] 打开机器人仿真失败：{exc}")
            QtWidgets.QMessageBox.critical(self, "无法打开机器人仿真", str(exc))
            return
        pid = getattr(self._robot_ui_process, "pid", "?")
        self._write_log(f"[UI] 已启动机器人仿真界面（PID {pid}）")

    def load_json_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择装箱算法 JSON",
            str(self.project_dir / "output"),
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not path:
            return
        try:
            self.load_json_file(Path(path))
            self.show_final_result()
            self._current_result_path = Path(path).resolve()
            self._live_result_path = self._current_result_path
            self.refresh_result_history(select_current=True)
            if hasattr(self, "file_info"):
                self.file_info.setText(f"当前结果：{Path(path).name}")
            if hasattr(self, "step_result"):
                self.step_result.set_state("done", f"手动加载：{Path(path).name}")
            self.workspace_tabs.setCurrentIndex(0)
        except Exception as exc:
            self.on_backend_failed(f"加载 JSON 失败：{exc}")

    def show_algorithm_settings_info(self) -> None:
        """Show current backend path/config in a plain dialog for non-technical users."""
        project = getattr(self, "project_dir", None)
        config = getattr(self, "config_path", None)
        excel = getattr(self, "selected_excel_original", None)
        out_path = getattr(self, "generated_out_path", None)
        msg = (
            "当前算法设置：\n\n"
            f"算法目录：{project}\n"
            f"配置文件：{config}\n"
            f"已选择 Excel：{excel or '尚未选择'}\n"
            f"本次输出：{out_path or '尚未生成'}\n\n"
            "日常使用只需要：选择Excel → 一键装箱。\n"
            "只有更换算法工程或 YAML 参数时，才需要修改这里。"
        )
        QtWidgets.QMessageBox.information(self, "算法设置", msg)

    # ------------------------------------------------------------------ Excel
    def choose_excel_file(self) -> Optional[Path]:
        start_dir = _project_data_dir(self.project_dir)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择装箱输入 Excel",
            str(start_dir if start_dir.exists() else self.project_dir),
            "Excel Files (*.xlsx *.xls);;All Files (*.*)",
        )
        if not path:
            return None
        try:
            original = Path(path).resolve()
            copied = _copy_excel_to_project_data(self.project_dir, original)
            run_mode, sheets, warnings = _read_excel_mode(copied)
            cfg = _write_ui_config(self.project_dir, self.project_dir / DEFAULT_CONFIG_REL, copied, run_mode)

            self.selected_excel_original = original
            self.selected_excel_copy = copied
            self.generated_config_path = cfg
            self.config_path = cfg
            self.last_excel_mode = run_mode

            self._write_log(f"[UI] 已选择 Excel：{original}")
            self._write_log(f"[UI] 已复制到项目数据目录：{copied}")
            self._write_log(f"[UI] 检测到工作表：{', '.join(sheets)}")
            self._write_log(f"[UI] 运行模式：{run_mode}")
            self._write_log(f"[UI] 已生成临时配置：{cfg}")
            for w in warnings:
                self._write_log(f"[警告] {w}")
            return cfg
        except Exception as exc:
            self.on_backend_failed(f"选择 Excel / 生成临时配置失败：{exc}")
            return None

    def start_excel_packing(self) -> None:
        run_mode = self._current_run_mode()
        policy = run_mode_policy(run_mode)
        if policy.uses_api:
            interval = normalize_download_interval(self.sp_download_interval.value())
            self.download_interval = interval
            cfg = _write_ui_config_api_only(
                self.project_dir,
                self.project_dir / DEFAULT_CONFIG_REL,
                interval,
            )
            self.generated_config_path = cfg
            self.config_path = cfg
            self._write_log(f"[UI] 接口模式：已生成临时配置 {cfg}")
            descriptions = {
                "continuous": f"每 {interval} 秒拉取并计算，直到手动停止",
                "once": "拉取并计算一次后停止",
                "until-success": (
                    f"每 {interval} 秒拉取并计算，出现成功托盘后自动停止"
                ),
            }
            self._write_log(f"[UI] 将启动：{descriptions[run_mode]}。")
        else:
            # 已经通过“选择Excel”选过文件时，直接运行；没有选过时再弹出选择框。
            if self.generated_config_path is None or self.selected_excel_copy is None:
                cfg = self.choose_excel_file()
                if cfg is None:
                    return
            else:
                self.config_path = self.generated_config_path
                self._write_log(f"[UI] 使用已选择 Excel：{self.selected_excel_original}")
        self.start_backend_packing(run_mode=run_mode)

    # ------------------------------------------------------------------ backend
    def start_backend_packing(self, run_mode: Optional[str] = None) -> None:
        if self.worker and self.worker.isRunning():
            QtWidgets.QMessageBox.information(self, "提示", "后端装箱正在运行。")
            return
        ensure_runtime_dirs(self.project_dir)
        if not isinstance(run_mode, str):
            run_mode = self._current_run_mode()
        policy = run_mode_policy(run_mode)
        self._active_run_mode = run_mode
        self._api_service_active = policy.uses_api
        out_path = None if policy.uses_api else _make_out_path(self.project_dir)
        self.generated_out_path = out_path
        self.worker = UiPackingWorker(
            self.project_dir,
            self.config_path,
            out_path=out_path,
            run_mode=run_mode,
            download_interval=self.download_interval,
            parent=self,
        )
        self.worker.log.connect(self._write_log)
        self.worker.started_cmd.connect(lambda cmd: self._write_log(f"[CMD] {cmd}"))
        self.worker.failed.connect(self.on_backend_failed)
        self.worker.finished_json.connect(self.on_backend_finished_json)
        self.worker.finished.connect(self.on_worker_finished)

        self.btn_start_backend.setEnabled(False)
        if hasattr(self, "action_rerun_config"):
            self.action_rerun_config.setEnabled(False)
        if hasattr(self, "btn_algo_settings"):
            self.btn_algo_settings.setEnabled(False)
        if hasattr(self, "btn_excel_run"):
            self.btn_excel_run.setEnabled(False)
        if hasattr(self, "btn_excel"):
            self.btn_excel.setEnabled(False)
        if hasattr(self, "sp_download_interval"):
            self.sp_download_interval.setEnabled(False)
        if hasattr(self, "cmb_run_mode"):
            self.cmb_run_mode.setEnabled(False)
        self.btn_stop_backend.setEnabled(True)
        self.btn_stop_backend.setVisible(True)
        self.btn_load.setEnabled(False)
        if policy.uses_api:
            active_messages = {
                "continuous": f"接口持续运行：每 {self.download_interval} 秒拉取并装箱",
                "once": "接口单次运行：拉取并计算一次",
                "until-success": "接口运行至成功：等待出现成功托盘",
            }
            self.step_run.set_state("active", active_messages[run_mode])
        else:
            self.step_run.set_state("active", "后端装箱算法正在运行，完成后会自动显示结果")
        self._set_status("running")
        self._write_log("[UI] 开始后端装箱计算。")
        self._write_log(f"[UI] 使用配置：{self.config_path}")
        if policy.uses_api:
            self._write_log(f"[UI] 接口运行方式：{run_mode}")
        else:
            self._write_log(f"[UI] 指定输出：{self.generated_out_path}")
        self.worker.start()

    def stop_backend_packing(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._write_log("[UI] 正在停止后端装箱进程...")
            if self._api_service_active:
                self.step_run.set_state("active", "正在停止接口服务...")
                self._set_status("stopped")
            else:
                self.step_run.set_state("error", "已请求停止后端进程")
                self._set_status("stopped")

    def on_worker_finished(self) -> None:
        super().on_worker_finished()
        finished_mode = self._active_run_mode
        completed_ok = bool(self.worker and self.worker.completed_ok)
        stopped_by_user = bool(self.worker and self.worker.stopped_like_user)
        self._api_service_active = False
        self._active_run_mode = None
        if hasattr(self, "action_rerun_config"):
            self.action_rerun_config.setEnabled(True)
        if hasattr(self, "btn_algo_settings"):
            self.btn_algo_settings.setEnabled(True)
        if hasattr(self, "btn_excel_run"):
            self.btn_excel_run.setEnabled(True)
        if hasattr(self, "cmb_run_mode"):
            self.cmb_run_mode.setEnabled(True)
        self._apply_run_mode_controls()
        if hasattr(self, "btn_stop_backend"):
            self.btn_stop_backend.setEnabled(False)
            self.btn_stop_backend.setVisible(True)
        if finished_mode == "continuous" and (completed_ok or stopped_by_user):
            detail = (
                "真实接口失败，已停止"
                if self.worker and getattr(self.worker, "_api_forced_stop", False)
                else "接口持续服务已停止"
            )
            self.step_run.set_state("done", detail)
            self._set_status("stopped")
            self._write_log(f"[UI] {detail}。")
        elif completed_ok and finished_mode in {"once", "until-success"}:
            finished_messages = {
                "once": "接口单次运行已完成",
                "until-success": "已发现成功托盘，接口服务自动停止",
            }
            message = finished_messages[finished_mode]
            self.step_run.set_state("done", message)
            self._set_status("done", message)
            self._write_log(f"[UI] {message}。")
        elif stopped_by_user:
            self.step_run.set_state("done", "已停止")
            self._set_status("stopped")
            self._write_log("[UI] 接口服务已停止。")
        else:
            # 兜底：任意结束都退出忙碌进度条，避免蓝条空转
            if hasattr(self, "run_progress"):
                self.run_progress.setRange(0, 100)
                self.run_progress.setValue(0)
                self.run_progress.setFormat("已结束")

    def closeEvent(self, event) -> None:
        try:
            _stop_local_wcs_receiver(
                getattr(self, "_local_wcs_receiver_proc", None),
                self._write_log,
            )
        except Exception:
            pass
        self._local_wcs_receiver_proc = None
        super().closeEvent(event)

    def on_backend_finished_json(self, json_path: str) -> None:
        path = Path(json_path)
        self._write_log(f"[UI] 后端完成，正在自动加载结果：{path}")
        try:
            self.load_json_file(path)
            self.show_final_result()
            self._current_result_path = path.resolve()
            self._live_result_path = self._current_result_path
            self.refresh_result_history(select_current=True)
            if hasattr(self, "file_info"):
                self.file_info.setText(f"当前结果：{path.name}")
            if self._api_service_active:
                if self._active_run_mode == "continuous":
                    detail = f"已显示本轮结果（{path.name}），等待下一次计算"
                elif self._active_run_mode == "until-success":
                    detail = f"已显示本轮结果（{path.name}），检查成功托盘"
                else:
                    detail = f"已显示本次结果（{path.name}），即将停止"
                self.step_run.set_state("active", detail)
                self.step_result.set_state("done", f"最新结果：{path.name}")
                self._set_status("running")
            else:
                self.step_run.set_state("done", "后端完成，已直接显示最终三维结果")
                self.step_result.set_state("done", f"结果文件：{path.name}")
                self._set_status("done")
            self.workspace_tabs.setCurrentIndex(0)
        except Exception as exc:
            self.on_backend_failed(f"加载算法输出 JSON 失败：{exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Industrial Packing Workbench V3 Clean")
    parser.add_argument("--project", default=str(_PROJECT_DIR_DEFAULT), help="packing-system repo root")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Industrial Packing Workbench V3")
    win = IndustrialPackingWorkbenchClean(Path(args.project))
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
