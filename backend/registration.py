"""Attendance state (derived from the log) and the registration rules.

Every operator action ends in exactly one of:
  - success   -> a signed checkin / checkout / walkin entry
  - rejected  -> a signed `rejected` entry with the official reason (FORMAT.md section 3)
  - invalid   -> nothing is written (empty or unparseable input, e.g. a typo like "ABC")

Rejections are decided by the station's own state, never by an operator choosing a reason.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .validation import CODE_RE, ROLES, WALKIN_RE

if TYPE_CHECKING:  # pragma: no cover
    from .station import Station

# Loose pattern: anything shaped like a code is treated as "a code was given".
# Strict CODE_RE is applied by the code list itself (unknown -> unknown_code).
LOOSE_CODE_RE = re.compile(r"^[A-Z0-9]{3}-[A-Z0-9]{3}$")
MAX_NAME = 120
MAX_SKILL = 120


# --------------------------------------------------------------------------- state

@dataclass
class AttendanceState:
    active: dict = field(default_factory=dict)        # ("code"|"walkin_id", id) -> info
    walkins: dict = field(default_factory=dict)       # walkin_id -> {"name","role","skill"}
    paper_keys: set = field(default_factory=set)      # (sheet, line)
    counts: dict = field(default_factory=lambda: {"checkin": 0, "checkout": 0, "walkin": 0, "rejected": 0})
    rejected_by_reason: dict = field(default_factory=dict)
    last_handover_seq: int = 0
    last_seq: int = 0

    @classmethod
    def replay(cls, entries) -> "AttendanceState":
        st = cls()
        for e in entries:
            st.apply(e)
        return st

    @staticmethod
    def key_of(payload: dict):
        if "code" in payload:
            return ("code", payload["code"])
        if "walkin_id" in payload:
            return ("walkin_id", payload["walkin_id"])
        return None

    def apply(self, e: dict) -> None:
        t, p = e["type"], e["payload"]
        self.last_seq = e["seq"]
        src = p.get("source") if isinstance(p, dict) else None
        if isinstance(src, dict) and src.get("kind") == "paper":
            self.paper_keys.add((src.get("sheet"), src.get("line")))
        if t == "checkin":
            self.counts["checkin"] += 1
            self.active[self.key_of(p)] = {"since": e["recorded_at"], "seq": e["seq"]}
        elif t == "checkout":
            self.counts["checkout"] += 1
            self.active.pop(self.key_of(p), None)
        elif t == "walkin":
            self.counts["walkin"] += 1
            self.walkins[p["walkin_id"]] = {"name": p["name"], "role": p["role_claimed"], "skill": p["skill"]}
            self.active[("walkin_id", p["walkin_id"])] = {"since": e["recorded_at"], "seq": e["seq"]}
        elif t == "rejected":
            self.counts["rejected"] += 1
            r = p["reason"]
            self.rejected_by_reason[r] = self.rejected_by_reason.get(r, 0) + 1
        elif t == "handover":
            self.last_handover_seq = e["seq"]

    def is_active(self, key) -> bool:
        return key in self.active


# --------------------------------------------------------------------------- results

@dataclass
class Outcome:
    status: str            # "success" | "rejected" | "invalid"
    message: str
    entry: dict | None = None
    reason: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def as_dict(self) -> dict:
        d = {"status": self.status, "message": self.message}
        if self.reason:
            d["reason"] = self.reason
        if self.entry:
            d["seq"] = self.entry["seq"]
            d["type"] = self.entry["type"]
            d["recorded_at"] = self.entry["recorded_at"]
        d.update(self.extra)
        return d


# --------------------------------------------------------------------------- input parsing

def normalize_identifier(raw) -> tuple[str, str] | None:
    """Return ("code", "ABC-DEF") or ("walkin_id", "W-T1-0001"), or None if unusable.

    Accepts lower case, spaces, missing dash ("abcdef") and common separators.
    """
    if not isinstance(raw, str):
        return None
    s = unicodedata.normalize("NFKC", raw).strip().upper()
    s = re.sub(r"[\s_]+", "", s).replace("–", "-").replace("—", "-")
    if not s:
        return None
    if s.startswith("W-") or re.match(r"^W[A-Z0-9]+-?\d{4}$", s):
        m = re.match(r"^W-?([A-Z0-9]+?)-?(\d{4})$", s)
        if m:
            w = f"W-{m.group(1)}-{m.group(2)}"
            if WALKIN_RE.match(w):
                return ("walkin_id", w)
        return None
    if re.match(r"^[A-Z0-9]{6}$", s):
        s = s[:3] + "-" + s[3:]
    if LOOSE_CODE_RE.match(s):
        return ("code", s)
    return None


def _source(source: dict | None) -> dict:
    return dict(source) if source else {"kind": "station"}


def _with_paper(payload: dict, occurred_at: str | None) -> dict:
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at
    return payload


# --------------------------------------------------------------------------- operations

def _reject(st: "Station", attempt: str, reason: str, ident: tuple | None, source: dict,
            occurred_at: str | None, message: str, note: str | None = None) -> Outcome:
    payload = {"attempt": attempt, "reason": reason}
    if ident:
        payload[ident[0]] = ident[1]
    if note:
        payload["note"] = note
    payload["source"] = source
    _with_paper(payload, occurred_at)
    entry = st.append("rejected", payload)
    return Outcome("rejected", message, entry, reason)


def checkin(st: "Station", raw, *, source: dict | None = None, occurred_at: str | None = None) -> Outcome:
    src = _source(source)
    ident = normalize_identifier(raw)
    if ident is None:
        return Outcome("invalid", "Not a code (expected XXX-XXX) or walk-in ID (W-T1-0001). Nothing recorded.")
    with st.write_lock:
        kind, value = ident
        if kind == "code":
            if value not in st.codes:
                return _reject(st, "checkin", "unknown_code", ident, src, occurred_at,
                               f"REJECTED: {value} is not on the code list.")
        elif value not in st.state.walkins:
            return _reject(st, "checkin", "other", None, src, occurred_at,
                           f"REJECTED: walk-in ID {value} was never issued at this station.",
                           note=f"unknown walk-in ID {value} (never issued at this station)")
        if st.state.is_active(ident):
            return _reject(st, "checkin", "already_checked_in", ident, src, occurred_at,
                           f"REJECTED: {value} is already checked in.")
        payload = {kind: value, "source": src}
        entry = st.append("checkin", _with_paper(payload, occurred_at))
        info = st.codes.get(value) or st.state.walkins.get(value) or {}
        return Outcome("success", f"Checked in: {value}", entry,
                       extra={"role": info.get("role", ""), "skill": info.get("skill", "")})


def checkout(st: "Station", raw, *, source: dict | None = None, occurred_at: str | None = None) -> Outcome:
    src = _source(source)
    ident = normalize_identifier(raw)
    if ident is None:
        return Outcome("invalid", "Not a code (expected XXX-XXX) or walk-in ID (W-T1-0001). Nothing recorded.")
    with st.write_lock:
        kind, value = ident
        if kind == "code" and value not in st.codes:
            return _reject(st, "checkout", "unknown_code", ident, src, occurred_at,
                           f"REJECTED: {value} is not on the code list.")
        if kind == "walkin_id" and value not in st.state.walkins:
            return _reject(st, "checkout", "other", None, src, occurred_at,
                           f"REJECTED: walk-in ID {value} was never issued at this station.",
                           note=f"unknown walk-in ID {value} (never issued at this station)")
        if not st.state.is_active(ident):
            return _reject(st, "checkout", "not_checked_in", ident, src, occurred_at,
                           f"REJECTED: {value} is not checked in here.")
        payload = {kind: value, "source": src}
        entry = st.append("checkout", _with_paper(payload, occurred_at))
        return Outcome("success", f"Checked out: {value}", entry)


def next_walkin_id(st: "Station") -> str:
    prefix = f"W-{st.team_id}-"
    highest = st.cfg.walkin_start - 1
    for w in st.state.walkins:
        if w.startswith(prefix):
            highest = max(highest, int(w[len(prefix):]))
    n = highest + 1
    if n > 9999:
        raise RuntimeError("walk-in ID space exhausted")
    return f"{prefix}{n:04d}"


def _clean_text(v, limit: int) -> str:
    if not isinstance(v, str):
        return ""
    v = unicodedata.normalize("NFC", v)
    v = "".join(ch for ch in v if unicodedata.category(ch)[0] != "C")
    return " ".join(v.split())[:limit]


def walkin(st: "Station", *, name, role, skill, consent, source: dict | None = None,
           occurred_at: str | None = None) -> Outcome:
    src = _source(source)
    with st.write_lock:
        if consent is not True:
            # No name, no role, no ID: data minimisation (FORMAT.md: "Bei no_consent keinen Namen speichern").
            return _reject(st, "walkin", "no_consent", None, src, occurred_at,
                           "REJECTED: no consent. Nothing about the person was stored.")
        name_c = _clean_text(name, MAX_NAME)
        skill_c = _clean_text(skill, MAX_SKILL)
        if not name_c:
            return Outcome("invalid", "Please enter the person's name. Nothing recorded.")
        if role not in ROLES:
            return Outcome("invalid", "Please choose a role: gruen, gelb or rot. Nothing recorded.")
        wid = next_walkin_id(st)
        payload = {"walkin_id": wid, "name": name_c, "role_claimed": role, "skill": skill_c,
                   "consent": True, "consent_version": st.cfg.consent_version, "source": src}
        entry = st.append("walkin", _with_paper(payload, occurred_at))
        return Outcome("success", f"Walk-in registered and checked in: {wid}", entry,
                       extra={"walkin_id": wid})


__all__ = ["AttendanceState", "Outcome", "normalize_identifier", "checkin", "checkout", "walkin",
           "next_walkin_id", "CODE_RE"]
