import argparse
import os

os.environ.setdefault("QT_API", "pyside6")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="机器人装箱三维仿真")
    parser.add_argument("--plan", default=None, help="启动时加载的装箱方案 JSON")
    parser.add_argument(
        "--command-file",
        default=None,
        help="现场码垛指令文件（仪表盘写入，本程序轮询）",
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

    return run(plan_path=args.plan, command_file=args.command_file)


if __name__ == "__main__":
    raise SystemExit(main())
