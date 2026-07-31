from __future__ import annotations

import sys

import app_launcher


def test_source_runtime_keeps_packing_path_first(monkeypatch, tmp_path):
    """源码启动必须让 packing/src 胜过顶层同名 src。"""
    root = tmp_path / "packing-system"
    for rel in ("packing", "ui", "local_wcs_receiver", "config"):
        (root / rel).mkdir(parents=True)
    workspace = tmp_path / "packing-workspace"

    monkeypatch.setattr(app_launcher, "is_frozen", lambda: False)
    monkeypatch.setattr(app_launcher, "app_root", lambda: root)
    monkeypatch.setattr(app_launcher, "bundle_root", lambda: root)
    monkeypatch.setenv("PACKING_WORKSPACE", str(workspace))
    original = list(sys.path)
    try:
        app_launcher.ensure_runtime_env()
        expected = [
            str(root / "packing"),
            str(root / "ui"),
            str(root / "local_wcs_receiver"),
            str(root),
        ]
        assert sys.path[:4] == expected
    finally:
        sys.path[:] = original
