"""Runtime configuration, read from environment variables (and an optional .env file).

Secrets (team token) are ONLY read from the environment / .env, never from code,
and are never written to logs or returned by any HTTP endpoint.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_VERSION = "1.0.0"
DEFAULT_API_BASE = "https://hackathon.ortsbereit.de"


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Config:
    data_dir: Path
    codelist_path: Path
    api_base: str
    team_token: str | None
    station_id: str | None
    team_id: str | None
    timezone: str
    mode: str                  # "live" or "rehearsal"
    walkin_start: int          # first walk-in number (use >1 on a replacement device)
    consent_version: str
    phone_challenge_ttl_s: int
    host: str
    port: int

    @property
    def key_path(self) -> Path:
        return self.data_dir / "station_key.json"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "log.jsonl"

    @property
    def station_path(self) -> Path:
        return self.data_dir / "station.json"

    @property
    def sync_path(self) -> Path:
        return self.data_dir / "sync_state.json"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / ".station.lock"


def load_config(**overrides) -> Config:
    load_dotenv(ROOT / ".env")
    env = os.environ
    data_dir = Path(overrides.pop("data_dir", None) or env.get("RESQ_DATA_DIR") or ROOT / "data" / "live")
    cfg = Config(
        data_dir=Path(data_dir),
        codelist_path=Path(env.get("RESQ_CODELIST") or ROOT / "data" / "codeliste.json"),
        api_base=(env.get("RESQ_API_BASE") or DEFAULT_API_BASE).rstrip("/"),
        team_token=env.get("RESQ_TEAM_TOKEN") or None,
        station_id=env.get("RESQ_STATION_ID") or None,
        team_id=env.get("RESQ_TEAM_ID") or None,
        timezone=env.get("RESQ_TIMEZONE") or "Europe/Berlin",
        mode=(env.get("RESQ_MODE") or "live").lower(),
        walkin_start=int(env.get("RESQ_WALKIN_START") or 1),
        consent_version=env.get("RESQ_CONSENT_VERSION") or "1.0",
        phone_challenge_ttl_s=int(env.get("RESQ_PHONE_TTL") or 90),
        host=env.get("RESQ_HOST") or "127.0.0.1",
        port=int(env.get("RESQ_PORT") or 5000),
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg
