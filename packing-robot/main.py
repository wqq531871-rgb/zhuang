import argparse
import os

os.environ.setdefault("QT_API", "pyside6")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="现场码垛三维演示 / PLC 通讯")
    parser.add_argument(
        "--plan",
        default=None,
        help="已废弃：不再从外部 JSON 加载",
    )
    parser.add_argument(
        "--command-file",
        default=None,
        help="现场码垛指令文件（仪表盘写入，本程序轮询）",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="packing_config.yaml（含 database）；默认读 packing-system/config",
    )
    parser.add_argument(
        "--plc-window",
        action="store_true",
        help="仅打开 PLC 通讯独立窗口（不启三维）",
    )
    parser.add_argument(
        "--auto-connect",
        action="store_true",
        help="PLC 窗口启动后自动连接并进入等信号下发",
    )
    args = parser.parse_args(argv)

    try:
        import PySide6  # noqa: F401
    except ImportError:
        print(
            "缺少 PySide6。请在本 Python 环境执行：\n"
            "  python -m pip install -r requirements.txt\n"
            f"当前解释器：{os.sys.executable}"
        )
        return 1

    if args.plc_window:
        from packing_ui.plc_window import run as run_plc

        return run_plc(
            command_file=args.command_file,
            config_path=args.config,
            auto_connect=bool(args.auto_connect),
        )

    from packing_ui.main_window import run

    return run(command_file=args.command_file, config_path=args.config)


if __name__ == "__main__":
    raise SystemExit(main())
