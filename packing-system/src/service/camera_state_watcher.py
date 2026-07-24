# -*- coding: utf-8 -*-
"""接法 B：监听 camera_* 已写入、state 仍空 → 自动判写 state。

PLC 下传仍由 PlcStateWatcher 负责（只处理 state=1/2）。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

from src.service.box_camera_state_db import (
    DEFAULT_DIM_TOLERANCE_MM,
    auto_judge_pending_camera_rows,
)
from src.service.success_box_db import DatabaseConfig


class CameraStateWatcher:
    """后台线程：轮询 camera 就绪未判态箱并写 state。"""

    def __init__(
        self,
        *,
        config_path: Optional[Path] = None,
        db_config: Optional[DatabaseConfig] = None,
        poll_interval_sec: float = 0.5,
        enabled: bool = True,
        tol_mm: float = DEFAULT_DIM_TOLERANCE_MM,
    ) -> None:
        self._config_path = Path(config_path) if config_path else None
        self._db_config = db_config
        self._interval = max(0.1, float(poll_interval_sec))
        self._enabled = bool(enabled)
        self._tol_mm = float(tol_mm)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_tick: Dict[str, Any] = {}

    @property
    def last_tick(self) -> Dict[str, Any]:
        return dict(self._last_tick)

    def start(self) -> None:
        if not self._enabled:
            print("[判态监听] 已关闭（state_judge.enabled=false）")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="CameraStateWatcher",
            daemon=True,
        )
        self._thread.start()
        print(
            f"[判态监听] 已启动，每 {self._interval:g}s 检查 "
            f"camera_* 齐全且 state 为空 → 自动判定"
        )

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        print("[判态监听] 已停止")

    def tick_once(self) -> Dict[str, Any]:
        result = auto_judge_pending_camera_rows(
            config_path=self._config_path,
            db_config=self._db_config,
            tol_mm=self._tol_mm,
        )
        self._last_tick = result
        return result

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.tick_once()
                judged = int(result.get("judged") or 0)
                if judged > 0:
                    print(
                        f"[判态监听] 本轮判定 {judged} 箱 "
                        f"（待处理扫描 {result.get('pending', 0)}）"
                    )
            except Exception as exc:
                print(f"[判态监听] 本轮失败：{exc}")
                self._last_tick = {"ok": False, "error": str(exc)}
            self._stop.wait(self._interval)
