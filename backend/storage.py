"""Durable local storage: station key, append-only signed JSONL log, small state files.

Design decisions
- The signed JSONL log is the single source of truth. All attendance state is derived
  by replaying it, so there is no second database that could disagree with the log.
- Every append is written in binary mode (exact "\n" line endings, also on Windows),
  flushed and fsync'ed before the operator sees "success".
- A torn final line (power loss mid-write) is detected on start, moved to a
  `log.jsonl.torn-<time>` file for audit and truncated. That entry was never confirmed
  to the operator because confirmation only happens after fsync.
- Any other unreadable line is NOT auto-repaired: the station refuses to write and the
  readiness screen shows the problem (never silently modify history).
- One process at a time: an OS-level exclusive lock file prevents two app instances (or
  the app plus the CLI) from writing conflicting sequence numbers. Inside the process a
  threading lock serialises appends.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import crypto


class StorageError(RuntimeError):
    pass


class LockError(StorageError):
    pass


# --------------------------------------------------------------------------- small helpers

def atomic_write_json(path: Path, data, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode or 0o644)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


class ProcessLock:
    """Exclusive, non-blocking, cross-platform lock on a file."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise LockError(
                f"Another RESQ process is already using {self.path.parent}. "
                "Stop it first (only one writer is allowed)."
            ) from exc
        self._fh = fh

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


# --------------------------------------------------------------------------- key store

class KeyStore:
    """Holds the station's Ed25519 private key on disk (32-byte seed, hex)."""

    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self):
        data = read_json(self.path)
        if not data:
            raise StorageError(f"No station key at {self.path}")
        key = crypto.private_key_from_seed(bytes.fromhex(data["seed_hex"]))
        pub = crypto.public_key_b64(key)
        if data.get("public_key_b64") and data["public_key_b64"] != pub:
            raise StorageError("Key file is inconsistent: stored public key does not match seed")
        if pub == crypto.PUBLIC_TEST_KEY_B64:
            raise StorageError("Refusing to use the public T1 TEST key as a station key")
        return key

    def public_key_b64(self) -> str:
        return crypto.public_key_b64(self.load())

    def save_new(self, private_key, *, overwrite: bool = False, note: str = "") -> str:
        if self.exists() and not overwrite:
            raise StorageError(
                f"A station key already exists at {self.path}. Refusing to overwrite it "
                "(a registered key must never be regenerated)."
            )
        pub = crypto.public_key_b64(private_key)
        if pub == crypto.PUBLIC_TEST_KEY_B64:
            raise StorageError("Refusing to store the public T1 TEST key as a station key")
        atomic_write_json(self.path, {
            "seed_hex": crypto.seed_bytes(private_key).hex(),
            "public_key_b64": pub,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "note": note or "PRIVATE. Never commit, never share, never upload.",
        }, mode=0o600)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return pub


# --------------------------------------------------------------------------- event log

class EventLog:
    """Append-only JSON Lines log of sealed entries."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: list[dict] = []
        self.corruption: str | None = None
        self.recovered_fragment: Path | None = None
        self._lock = threading.RLock()

    # -- loading / recovery
    def load(self) -> "EventLog":
        with self._lock:
            self.entries = []
            self.corruption = None
            if not self.path.exists():
                return self
            data = self.path.read_bytes()
            if data and not data.endswith(b"\n"):
                cut = data.rfind(b"\n") + 1
                fragment = data[cut:]
                frag_path = self.path.with_name(f"{self.path.name}.torn-{int(time.time())}")
                frag_path.write_bytes(fragment)
                with open(self.path, "r+b") as fh:
                    fh.truncate(cut)
                    fh.flush()
                    os.fsync(fh.fileno())
                self.recovered_fragment = frag_path
                data = data[:cut]
            for n, raw in enumerate(data.split(b"\n"), start=1):
                if not raw.strip():
                    continue
                try:
                    self.entries.append(json.loads(raw.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.corruption = f"line {n} of {self.path.name} is not valid JSON"
                    break
            if not self.corruption:
                for i, e in enumerate(self.entries, start=1):
                    if e.get("seq") != i:
                        self.corruption = f"entry {i} has seq {e.get('seq')} (expected {i})"
                        break
            return self

    # -- reading
    def __len__(self):
        return len(self.entries)

    @property
    def last(self) -> dict | None:
        return self.entries[-1] if self.entries else None

    def next_seq(self) -> int:
        return len(self.entries) + 1

    def prev_hash(self) -> str:
        return self.entries[-1]["hash"] if self.entries else crypto.GENESIS_PREV_HASH

    def lines(self, from_seq: int = 1) -> list[bytes]:
        return [crypto.canonical(e) for e in self.entries if e["seq"] >= from_seq]

    def ndjson(self, from_seq: int = 1) -> bytes:
        return b"".join(line + b"\n" for line in self.lines(from_seq))

    # -- writing
    def append(self, *, station_id: str, type_: str, payload: dict, recorded_at: str,
               private_key) -> dict:
        """Build, seal and durably append one entry. Returns the sealed entry."""
        with self._lock:
            if self.corruption:
                raise StorageError(f"Log is damaged ({self.corruption}); refusing to write.")
            entry = {
                "v": 1,
                "station_id": station_id,
                "seq": self.next_seq(),
                "type": type_,
                "recorded_at": recorded_at,
                "payload": payload,
                "prev_hash": self.prev_hash(),
            }
            sealed = crypto.seal(entry, private_key)
            line = crypto.canonical(sealed) + b"\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            size_before = self.path.stat().st_size if self.path.exists() else 0
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o644)
            try:
                written = os.write(fd, line)
                if written != len(line):
                    raise StorageError("short write to log")
                os.fsync(fd)
            except Exception:
                # roll back a partial line so the file stays a clean prefix of the chain
                try:
                    os.ftruncate(fd, size_before)
                    os.fsync(fd)
                except OSError:
                    pass
                raise
            finally:
                os.close(fd)
            self.entries.append(sealed)
            return sealed
