import argparse
import os

os.environ.setdefault("QT_API", "pyside6")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="现场码垛三维演示（从数据库加载）")
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

    from packing_ui.main_window import run

    return run(command_file=args.command_file, config_path=args.config)


if __name__ == "__main__":
    raise SystemExit(main())
