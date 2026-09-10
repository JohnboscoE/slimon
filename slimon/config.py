"""Configuration: committed TOML for behaviour, .env for secrets and the trading gate."""

from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "agent.toml"
# Overridable so tests and dev runs never write into the published log.
LOG_DIR = Path(os.environ.get("SLIMON_LOG_DIR") or ROOT / "logs")
STATE_DIR = Path(os.environ.get("SLIMON_STATE_DIR") or ROOT / "state")
KILL_SWITCH_PATH = ROOT / "STOP"


@dataclass(frozen=True)
class Secrets:
    bitget_key: str = field(repr=False)
    bitget_secret: str = field(repr=False)
    bitget_passphrase: str = field(repr=False)
    anthropic_key: str = field(repr=False)

    @property
    def has_bitget(self) -> bool:
        return bool(self.bitget_key and self.bitget_secret and self.bitget_passphrase)

    def values(self) -> list[str]:
        """Every secret value, for the log scrubber. Short values are ignored to avoid false hits."""
        return [v for v in (self.bitget_key, self.bitget_secret, self.bitget_passphrase, self.anthropic_key) if len(v) >= 8]


@dataclass(frozen=True)
class Config:
    raw: dict
    config_hash: str
    secrets: Secrets
    enable_trading: bool
    auto_commit_log: bool
    auto_push: bool

    @property
    def agent(self) -> dict:
        return self.raw["agent"]

    @property
    def perception(self) -> dict:
        return self.raw["perception"]

    @property
    def risk(self) -> dict:
        return self.raw["risk"]

    @property
    def sim(self) -> dict:
        return self.raw["sim"]

    @property
    def publish(self) -> dict:
        return self.raw["publish"]

    @property
    def mode(self) -> str:
        """sim: no Bitget key, local paper book. dry_run: real demo account, orders not sent.
        live_demo: orders sent to the Bitget demo venue."""
        if self.enable_trading:
            return "live_demo"
        return "dry_run" if self.secrets.has_bitget else "sim"


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    data = CONFIG_PATH.read_bytes()
    raw = tomllib.loads(data.decode("utf-8"))
    secrets = Secrets(
        bitget_key=os.environ.get("BITGET_API_KEY", "").strip(),
        bitget_secret=os.environ.get("BITGET_API_SECRET", "").strip(),
        bitget_passphrase=os.environ.get("BITGET_API_PASSPHRASE", "").strip(),
        anthropic_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
    )
    cfg = Config(
        raw=raw,
        config_hash=hashlib.sha256(data).hexdigest()[:12],
        secrets=secrets,
        enable_trading=_flag("ENABLE_TRADING"),
        auto_commit_log=_flag("AUTO_COMMIT_LOG"),
        auto_push=_flag("AUTO_PUSH"),
    )
    if cfg.enable_trading and not secrets.has_bitget:
        raise SystemExit("ENABLE_TRADING=1 but Bitget demo credentials are missing from .env")
    unknown = set(cfg.agent["whitelist"]) - set(cfg.agent["watchlist"])
    if unknown:
        raise SystemExit(f"whitelist symbols missing from watchlist: {sorted(unknown)}")
    return cfg
