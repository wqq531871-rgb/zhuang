"""Tests for launching packing-robot from the packing-system dashboard."""

from pathlib import Path

import pytest

from robot_ui_launcher import default_robot_directory, launch_robot_ui


class FakeProcess:
    def poll(self):
        return None


def test_default_robot_directory_points_at_sibling_packing_robot():
    robot_dir = default_robot_directory()
    assert robot_dir.name == "packing-robot"
    assert (robot_dir / "main.py").is_file()


def test_launcher_starts_robot_with_script_and_working_directory(tmp_path, monkeypatch):
    script = tmp_path / "main.py"
    script.write_text("# test", encoding="utf-8")
    calls = []

    process = launch_robot_ui(
        directory=tmp_path,
        python_executable=Path("C:/Python/python.exe"),
        popen_factory=lambda *args, **kwargs: (
            calls.append((args, kwargs)) or FakeProcess()
        ),
    )

    assert isinstance(process, FakeProcess)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ([str(Path("C:/Python/python.exe")), str(script)],)
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["QT_API"] == "pyside6"


def test_launcher_rejects_missing_robot(tmp_path):
    with pytest.raises(FileNotFoundError, match="机器人仿真程序不存在"):
        launch_robot_ui(directory=tmp_path)
