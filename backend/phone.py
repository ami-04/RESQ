"""Phone check-in (bonus task) with a live station challenge.

How it works
1. The station screen shows a short challenge (4 characters) that changes every
   ROTATE_S seconds. Challenges are random, kept only in memory, and expire after
   the configured TTL (default 90 s).
2. The helper opens the offline phone page (/phone, served by the station on the local
   network or saved earlier), types their personal code and the challenge they can SEE on
   the station screen. The phone shows a large check-in pass: code + challenge.
3. The operator types code + challenge from the pass. The station accepts only if the
   challenge was issued by this station within the TTL and this code has not used it yet.

What it proves, honestly: the person holding the phone (or someone talking to them live)
saw this station's screen within the last ~90 seconds. A photo or forwarded screenshot of
an earlier pass carries an old challenge and is rejected as `remote_suspected`.
What it does NOT prove: identity, or that the code owner is the person in front of you;
a live video call relaying the challenge defeats it. See docs/threat-model.md.
"""
from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

from . import registration as reg
from .registration import Outcome
from .validation import CODE_ALPHABET

if TYPE_CHECKING:  # pragma: no cover
    from .station import Station

ROTATE_S = 30
CHALLENGE_LEN = 4
METHOD = "station_challenge_v1"


class ChallengeBoard:
    def __init__(self, ttl_s: int = 90, rotate_s: int = ROTATE_S, clock=time.monotonic, wall=time.time):
        self.ttl_s = ttl_s
        self.rotate_s = rotate_s
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._issued: dict[str, tuple[float, float]] = {}  # challenge -> (monotonic, wall)
        self._used: set[tuple[str, str]] = set()
        self._current: str | None = None
        self._current_at = 0.0

    def _new(self) -> str:
        while True:
            c = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CHALLENGE_LEN))
            if c not in self._issued:
                return c

    def current(self) -> dict:
        with self._lock:
            now = self._clock()
            if self._current is None or now - self._current_at >= self.rotate_s:
                self._current = self._new()
                self._current_at = now
                self._issued[self._current] = (now, self._wall())
            self._expire(now)
            return {"challenge": self._current,
                    "rotates_in_s": max(0, int(self.rotate_s - (now - self._current_at)))}

    def _expire(self, now: float) -> None:
        for c, (t, _) in list(self._issued.items()):
            if now - t > self.ttl_s:
                del self._issued[c]
        self._used = {(code, ch) for code, ch in self._used if ch in self._issued}

    def check(self, code: str, challenge: str) -> tuple[bool, str, int, float | None]:
        """Return (valid, why, age_s, issued_wall)."""
        with self._lock:
            now = self._clock()
            self._expire(now)
            issued = self._issued.get(challenge)
            if issued is None:
                return False, "challenge unknown or expired", -1, None
            if (code, challenge) in self._used:
                return False, "challenge already used for this code (replay)", int(now - issued[0]), issued[1]
            return True, "ok", int(now - issued[0]), issued[1]

    def mark_used(self, code: str, challenge: str) -> None:
        with self._lock:
            self._used.add((code, challenge))


def phone_checkin(st: "Station", board: ChallengeBoard, code_raw, challenge_raw) -> Outcome:
    ident = reg.normalize_identifier(code_raw)
    if ident is None or ident[0] != "code":
        return Outcome("invalid", "The phone pass must show a code like XXX-XXX. Nothing recorded.")
    challenge = "".join((challenge_raw or "").split()).upper()
    if not challenge:
        return Outcome("invalid", "Type the challenge shown on the phone pass. Nothing recorded.")
    code = ident[1]
    with st.write_lock:
        valid, why, age, issued_wall = board.check(code, challenge)
        if not valid:
            proof = {"method": METHOD, "challenge": challenge[:16], "result": why}
            payload = {"attempt": "checkin", "reason": "remote_suspected", "code": code,
                       "source": {"kind": "phone", "proof": proof}}
            entry = st.append("rejected", payload)
            return Outcome("rejected",
                           f"REJECTED: phone pass not live ({why}). Looks like a forwarded or old screenshot.",
                           entry, "remote_suspected")
        issued_iso = datetime.fromtimestamp(issued_wall, st.tz).replace(microsecond=0).isoformat()
        proof = {"method": METHOD, "challenge": challenge, "issued_at": issued_iso, "age_s": max(0, age)}
        out = reg.checkin(st, code, source={"kind": "phone", "proof": proof})
        if out.entry is not None:
            board.mark_used(code, challenge)
        return out
