# -*- coding: utf-8 -*-
"""监听 ``wcs_success_box.state``：有 1/2 后自动构造并下传 PLC。

设计：
- 接口4只登记箱子到达；
- 相机/判转由其它模块写 ``state``；
- 本模块轮询发现就绪箱 → 入队 → 按 seq 自动下传（当前为桩发送）。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.service.plc_queue_db import (
    auto_process_state_ready_boxes,
    get_plc_queue_repo,
)
from src.service.success_box_db import (
    DatabaseConfig,
    load_database_config_from_yaml,
)


class PlcStateWatcher:
    """后台线程：轮询 state 就绪箱并自动下传。"""

    def __init__(
        self,
        *,
        config_path: Optional[Path] = None,
        db_config: Optional[DatabaseConfig] = None,
        poll_interval_sec: float = 0.5,
        enabled: bool = True,
    ) -> None:
        self._config_path = Path(config_path) if config_path else None
        self._db_config = db_config
        self._interval = max(0.1, float(poll_interval_sec))
        self._enabled = bool(enabled)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_tick: Dict[str, Any] = {}

    @property
    def last_tick(self) -> Dict[str, Any]:
        return dict(self._last_tick)

    def start(self) -> None:
        if not self._enabled:
            print("[PLC监听] 已关闭（plc_auto.enabled=false）")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="PlcStateWatcher",
            daemon=True,
        )
        self._thread.start()
        print(
            f"[PLC监听] 已启动，每 {self._interval:g}s 检查 "
            f"wcs_success_box.state → 自动下传"
        )

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        print("[PLC监听] 已停止")

    def tick_once(self) -> Dict[str, Any]:
        """单次扫描（测试 / 手动触发）。"""
        result = auto_process_state_ready_boxes(
            config_path=self._config_path,
            db_config=self._db_config,
        )
        self._last_tick = result
        return result

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.tick_once()
                processed = int(result.get("processed") or 0)
                enqueued = int(result.get("enqueued") or 0)
                sent = int(result.get("sent") or 0)
                if enqueued > 0 or sent > 0:
                    print(
                        f"[PLC监听] 本轮处理：入队={enqueued} 下传={sent} "
                        f"等待序={result.get('waiting_order', 0)} "
                        f"（扫描 {result.get('ready', 0)} 箱）"
                    )
            except Exception as exc:
                print(f"[PLC监听] 本轮失败：{exc}")
                self._last_tick = {"ok": False, "error": str(exc)}
            self._stop.wait(self._interval)


def list_state_ready_preview(
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """调试：列出 state 已就绪、尚未 sent 的箱。"""
    cfg = db_config or load_database_config_from_yaml(config_path)
    return get_plc_queue_repo(db_config=cfg).list_state_ready_unsent(limit=limit)
