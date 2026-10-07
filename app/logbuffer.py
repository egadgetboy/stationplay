"""The most recent log entries, kept in memory for the Logs tab."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from .ffmpeg import redact

# Entries kept; the Logs tab shows the newest 200.
KEEP = 500


class RecentLogs(logging.Handler):
    def __init__(self, keep: int = KEEP) -> None:
        super().__init__(logging.INFO)
        self._entries: deque[dict[str, Any]] = deque(maxlen=keep)
        self._lock_entries = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                message += f" ({type(record.exc_info[1]).__name__}: {record.exc_info[1]})"
            entry = {
                "time": record.created,
                "level": "ERROR" if record.levelno >= logging.ERROR else record.levelname,
                "source": record.name,
                "message": redact(message),
            }
        except Exception:
            self.handleError(record)
            return
        with self._lock_entries:
            self._entries.append(entry)

    def entries(self, levels: set[str] | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """The newest `limit` entries (oldest first), optionally only those
        at the given levels."""
        with self._lock_entries:
            entries = list(self._entries)
        if levels:
            entries = [e for e in entries if e["level"] in levels]
        return entries[-limit:]


def install() -> RecentLogs:
    """Attaches the buffer to the root logger, once per process."""
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RecentLogs):
            return handler
    handler = RecentLogs()
    root.addHandler(handler)
    return handler


def as_text(entries: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['time']))} "
        f"{e['level']:<7} {e['source']}: {e['message']}"
        for e in entries
    )
