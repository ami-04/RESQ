"""Station identity, setup and the single write path into the log."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import APP_VERSION, Config
from . import crypto
from .registration import AttendanceState
from .storage import EventLog, KeyStore, ProcessLock, StorageError, atomic_write_json, read_json
from .validation import CODE_RE, ROLES, STATION_ID_RE, validate_entry_schema


class SetupError(RuntimeError):
    pass


def team_id_from_station_id(station_id: str) -> str:
    """ST-T1 -> T1, ST-T1B (replacement device) -> T1."""
    m = re.match(r"^ST-(T\d+)[A-Z]?$", station_id)
    if not m:
        raise SetupError(f"Cannot derive team id from station id {station_id!r}; set RESQ_TEAM_ID")
    return m.group(1)


def load_codelist(path: Path) -> dict[str, dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    codes: dict[str, dict] = {}
    for item in raw:
        code = item["code"]
        if not CODE_RE.match(code):
            raise SetupError(f"code list contains malformed code {code!r}")
        if item.get("role") not in ROLES:
            raise SetupError(f"code list entry {code} has unknown role {item.get('role')!r}")
        if code in codes:
            raise SetupError(f"code list contains duplicate {code}")
        codes[code] = {"role": item["role"], "skill": item.get("skill", "")}
    return codes


class Station:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self.keys = KeyStore(cfg.key_path)
        self.log = EventLog(cfg.log_path)
        self.codes: dict[str, dict] = {}
        self.codelist_error: str | None = None
        self.state = AttendanceState()
        self.meta: dict = {}
        self._private_key = None
        self._write_lock = threading.RLock()
        self._proc_lock = ProcessLock(cfg.lock_path)
        self.phone = None  # set by app (ChallengeBoard)

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def open(cls, cfg: Config, *, acquire_lock: bool = True) -> "Station":
        st = cls(cfg)
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        if acquire_lock:
            st._proc_lock.acquire()
        st.reload()
        return st

    def close(self) -> None:
        self._proc_lock.release()

    def reload(self) -> None:
        try:
            self.codes = load_codelist(self.cfg.codelist_path)
            self.codelist_error = None
        except Exception as exc:  # shown on readiness screen
            self.codes = {}
            self.codelist_error = str(exc)
        self.meta = read_json(self.cfg.station_path, {}) or {}
        self._private_key = self.keys.load() if self.keys.exists() else None
        self.log.load()
        self.state = AttendanceState.replay(self.log.entries)

    # ------------------------------------------------------------------ identity
    @property
    def station_id(self) -> str | None:
        return self.meta.get("station_id")

    @property
    def team_id(self) -> str | None:
        return self.meta.get("team_id")

    @property
    def initialised(self) -> bool:
        return bool(self.log.entries) and self.log.entries[0].get("type") == "genesis"

    def now(self) -> str:
        return datetime.now(self.tz).replace(microsecond=0).isoformat()

    def now_dt(self) -> datetime:
        return datetime.now(self.tz).replace(microsecond=0)

    # ------------------------------------------------------------------ setup
    def initialise(self, station_id: str, team_id: str | None = None) -> dict:
        """Write genesis (seq 1). Only allowed on an empty log with a key present."""
        with self._write_lock:
            if self.log.entries:
                raise SetupError("Log already started; genesis exists. Refusing to re-initialise.")
            if self._private_key is None:
                raise SetupError("No station key. Import your registered key first.")
            if not STATION_ID_RE.match(station_id or ""):
                raise SetupError(f"Invalid station id {station_id!r} (expected e.g. ST-T1)")
            team_id = team_id or team_id_from_station_id(station_id)
            self.meta = {
                "station_id": station_id,
                "team_id": team_id,
                "public_key_b64": crypto.public_key_b64(self._private_key),
                "mode": self.cfg.mode,
                "created_at": self.now(),
            }
            atomic_write_json(self.cfg.station_path, self.meta)
            return self._append("genesis", {
                "station_pubkey": self.meta["public_key_b64"],
                "team_id": team_id,
                "app_version": APP_VERSION,
            })

    # ------------------------------------------------------------------ the only write path
    def append(self, type_: str, payload: dict) -> dict:
        with self._write_lock:
            if not self.initialised:
                raise SetupError("Station not initialised (no genesis yet).")
            return self._append(type_, payload)

    def _append(self, type_: str, payload: dict) -> dict:
        if self._private_key is None:
            raise SetupError("No station key loaded.")
        # Validate BEFORE signing: we never write a malformed entry.
        probe = {"v": 1, "station_id": self.station_id, "seq": self.log.next_seq(), "type": type_,
                 "recorded_at": self.now(), "payload": payload, "prev_hash": self.log.prev_hash(),
                 "hash": "0" * 64, "sig": ""}
        problems = validate_entry_schema(probe)
        if problems:
            raise StorageError("internal: refusing to write malformed entry: " + "; ".join(problems))
        entry = self.log.append(station_id=self.station_id, type_=type_, payload=payload,
                                recorded_at=probe["recorded_at"], private_key=self._private_key)
        self.state.apply(entry)
        return entry

    @property
    def write_lock(self):
        return self._write_lock
