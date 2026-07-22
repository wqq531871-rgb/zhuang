"""请求落盘与控制台日志。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def ensure_log_dir(log_dir: Path) -> Path:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def log_request(
    *,
    log_dir: Path,
    save_requests: bool,
    endpoint: str,
    method: str,
    body: Optional[Dict[str, Any]],
    response: Dict[str, Any],
) -> Optional[Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    summary = {
        "time": stamp,
        "method": method,
        "endpoint": endpoint,
        "body": body,
        "response": response,
    }
    line = json.dumps(summary, ensure_ascii=False)
    print(f"[RECV] {method} {endpoint} body={body} -> {response.get('code')}")

    if not save_requests:
        return None

    ensure_log_dir(log_dir)
    safe_name = endpoint.strip("/").replace("/", "_") or "root"
    path = log_dir / f"{stamp}_{safe_name}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
