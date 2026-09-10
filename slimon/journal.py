"""Append-only journals (committed) and mutable runtime state (not committed)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import LOG_DIR, STATE_DIR


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Journal:
    """One JSON object per line, one file per UTC day. Lines are only ever appended."""

    def __init__(self, secrets: list[str]):
        self._secrets = secrets

    def _append(self, kind: str, record: dict, when: datetime) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=False, default=str)
        for s in self._secrets:
            if s in line:  # belt and braces: credentials must never reach the log
                line = line.replace(s, "[REDACTED]")
        path = LOG_DIR / kind / f"{when.astimezone(timezone.utc):%Y-%m-%d}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def event(self, record: dict, when: datetime) -> None:
        self._append("events", record, when)

    def tick(self, record: dict, when: datetime) -> None:
        self._append("decisions", record, when)

    def run(self, record: dict, when: datetime) -> None:
        self._append("runs", record, when)


class State:
    """Small JSON document persisted atomically after each tick."""

    def __init__(self, name: str = "state.json"):
        self.path: Path = STATE_DIR / name
        self.data: dict = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, key: str, default):
        return self.data.setdefault(key, default)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self.path)
