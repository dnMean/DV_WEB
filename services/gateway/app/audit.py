"""Append-only JSONL audit log of every tool invocation."""
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, *, request_id: str, user_id: Any, tool: str, arguments: Any, status: str,
              latency_ms: float, **extra: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "request_id": request_id, "user_id": user_id, "tool": tool, "arguments": arguments,
            "status": status, "latency_ms": latency_ms, **extra,
        }
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.exception("cannot write audit log to %s", self.path)

    def tail(self, limit: int) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in reversed(lines)]
