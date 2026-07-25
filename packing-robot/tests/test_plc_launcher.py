from pathlib import Path

import pytest

from packing_ui.plc_launcher import launch_plc_ui


class FakeProcess:
    def poll(self):
        return None


def test_launcher_starts_plc_window_with_main_script(tmp_path):
    script = tmp_path / "main.py"
    script.write_text("# test", encoding="utf-8")
    calls = []

    process = launch_plc_ui(
        directory=tmp_path,
        python_executable=Path("C:/Python/python.exe"),
        popen_factory=lambda *args, **kwargs: (
            calls.append((args, kwargs)) or FakeProcess()
        ),
    )

    assert isinstance(process, FakeProcess)
    assert calls == [
        (
            (
                [
                    str(Path("C:/Python/python.exe")),
                    str(script),
                    "--plc-window",
                    "--auto-connect",
                ],
            ),
            {"cwd": str(tmp_path)},
        )
    ]


def test_launcher_rejects_missing_main(tmp_path):
    with pytest.raises(FileNotFoundError, match="PLC 通讯程序不存在"):
        launch_plc_ui(directory=tmp_path)
