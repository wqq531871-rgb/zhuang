# -*- coding: utf-8 -*-
"""统一启动入口：开发态与 PyInstaller 冻结态共用。

用法:
  界面（默认）:
    python app_launcher.py
    PackingWorkbench.exe

  子进程模式（冻结后由界面拉起）:
    PackingWorkbench.exe --mode packing --config ... [--out ...]
    PackingWorkbench.exe --mode wcs --config ... --run-mode continuous
    PackingWorkbench.exe --mode receiver --config ...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """交付目录（exe 旁 / 开发时为 packing-system 根）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_root() -> Path:
    """打包资源目录（_MEIPASS）或开发源码根。"""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return app_root()


def ensure_runtime_env() -> Path:
    """设置工作区与导入路径，返回 app_root。"""
    root = app_root()
    bundle = bundle_root()

    os.environ.setdefault("PACKING_APP_ROOT", str(root))
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    if not os.environ.get("PACKING_WORKSPACE", "").strip():
        os.environ["PACKING_WORKSPACE"] = str(root / "packing-workspace")

    # 导入优先级：packing 算法源码(src) > ui > 本地接收端
    for p in (
        bundle / "packing",
        bundle,  # 冻结后 src/ 在 _MEIPASS/src
        bundle / "ui",
        bundle / "local_wcs_receiver",
    ):
        if p.exists():
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)
    root_s = str(root if not is_frozen() else bundle)
    if not is_frozen():
        # 开发态：优先 packing/
        pack = root / "packing"
        if pack.exists() and str(pack) not in sys.path:
            sys.path.insert(0, str(pack))
        if root_s not in sys.path:
            sys.path.insert(0, root_s)
        ui = root / "ui"
        if ui.exists() and str(ui) not in sys.path:
            sys.path.insert(0, str(ui))
        recv = root / "local_wcs_receiver"
        if recv.exists() and str(recv) not in sys.path:
            sys.path.insert(0, str(recv))

    ws = Path(os.environ["PACKING_WORKSPACE"])
    for sub in (
        "data",
        "input/raw",
        "output/success",
        "output/fail",
        "output/success_case",
        "runtime/packing-realtime/logs",
        "runtime/packing-realtime/temp",
        "runtime/packing-realtime/exports",
    ):
        (ws / sub).mkdir(parents=True, exist_ok=True)

    # 外部可编辑配置：优先 exe 旁的 config/
    ext_cfg = root / "config"
    if not ext_cfg.exists():
        bundled_cfg = bundle / "config"
        if bundled_cfg.exists():
            try:
                import shutil

                shutil.copytree(bundled_cfg, ext_cfg)
            except OSError:
                pass

    ext_recv = root / "local_wcs_receiver" / "config"
    if not ext_recv.exists():
        bundled_recv = bundle / "local_wcs_receiver" / "config"
        if bundled_recv.exists():
            try:
                import shutil

                shutil.copytree(bundled_recv, ext_recv)
            except OSError:
                pass

    return root


def _parse_mode(argv: list[str]) -> tuple[str, list[str]]:
    if not argv:
        return "ui", []
    if argv[0] == "--mode" and len(argv) >= 2:
        return argv[1].strip().lower(), argv[2:]
    if argv[0].startswith("--mode="):
        return argv[0].split("=", 1)[1].strip().lower(), argv[1:]
    return "ui", argv


def _run_ui(project: Path, argv: list[str]) -> int:
    # ui/ 已在 sys.path 上（开发 / 冻结均如此）
    from realtime_dashboard_v3_clean import main as ui_main  # type: ignore

    if "--project" not in argv:
        sys.argv = [sys.argv[0], "--project", str(project), *argv]
    else:
        sys.argv = [sys.argv[0], *argv]
    ui_main()
    return 0

def _run_packing(argv: list[str]) -> int:
    import run_packing as packing_mod  # type: ignore

    sys.argv = [sys.argv[0], *argv]
    if hasattr(packing_mod, "main"):
        return int(packing_mod.main(argv) or 0)
    # 兼容旧入口：仅有 __main__ 块时走其 CLI 解析逻辑
    if hasattr(packing_mod, "_parse_cli") and hasattr(packing_mod, "_run"):
        out_path, max_boxes, profile, safe_compare, config_path = packing_mod._parse_cli(argv)
        if profile:
            import cProfile
            import pstats

            pr = cProfile.Profile()
            pr.enable()
            report = packing_mod._run(out_path, max_boxes, safe_compare, config_path)
            pr.disable()
            pstats.Stats(pr).sort_stats("cumulative").print_stats(30)
        else:
            report = packing_mod._run(out_path, max_boxes, safe_compare, config_path)
        return 0 if report is not None else 1
    raise RuntimeError("run_packing 入口缺少 main()/_run()")


def _run_wcs(argv: list[str]) -> int:
    from run_wcs_service import main as wcs_main  # type: ignore

    return int(wcs_main(argv) or 0)


def _run_receiver(argv: list[str]) -> int:
    # 保证 local_wcs_receiver 为包根
    recv_root = bundle_root() / "local_wcs_receiver"
    if recv_root.exists() and str(recv_root) not in sys.path:
        sys.path.insert(0, str(recv_root))
    # 外部配置优先
    root = app_root()
    ext_cfg = root / "local_wcs_receiver" / "config" / "receiver_config.yaml"
    if ext_cfg.exists() and "--config" not in argv:
        argv = ["--config", str(ext_cfg), *argv]

    from run_receiver import main as receiver_main  # type: ignore

    return int(receiver_main(argv) or 0)


def main() -> int:
    root = ensure_runtime_env()
    mode, rest = _parse_mode(sys.argv[1:])

    if mode in ("ui", "dashboard", "gui"):
        return _run_ui(root, rest)
    if mode in ("packing", "pack", "run_packing"):
        return _run_packing(rest)
    if mode in ("wcs", "wcs_service", "api"):
        return _run_wcs(rest)
    if mode in ("receiver", "wcs_receiver", "local_receiver"):
        return _run_receiver(rest)

    print(f"未知模式: {mode}", file=sys.stderr)
    print("可用: ui | packing | wcs | receiver", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
