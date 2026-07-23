import os

os.environ.setdefault("QT_API", "pyside6")

from packing_ui.main_window import run


if __name__ == "__main__":
    raise SystemExit(run())
