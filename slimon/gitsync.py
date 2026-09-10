"""Commit the append-only logs as they accrue, so git history shows them growing in real time."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

from .config import ROOT, Config
from .journal import State, iso


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def maybe_commit(cfg: Config, state: State, now: datetime) -> None:
    if not cfg.auto_commit_log:
        return
    last = state.data.get("last_log_commit_at")
    if last and now - datetime.fromisoformat(last.replace("Z", "+00:00")) < timedelta(minutes=cfg.publish["commit_every_minutes"]):
        return
    try:
        _git("add", "--", "logs")
        # Pathspec-limited commit: only logs/ is ever committed by the agent.
        res = _git("commit", "-m", f"log: decision log through {iso(now)}", "--", "logs")
        if res.returncode == 0 and cfg.auto_push:
            push = _git("push", timeout=120)
            if push.returncode != 0:
                print(f"[gitsync] push failed: {push.stderr.strip()[:300]}", flush=True)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[gitsync] {type(e).__name__}: {e}", flush=True)
        return
    state.data["last_log_commit_at"] = iso(now)
    state.save()
