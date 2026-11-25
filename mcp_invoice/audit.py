"""An append-only record of what the assistant asked for and what happened.

JSON lines, one event per line. Writes are logged *before* they are sent: if the log cannot be written, the
write does not happen (fail closed).
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path


class AuditLog:
    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, event: str, tool: str, **fields) -> None:
        line = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, "tool": tool, **fields}
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
