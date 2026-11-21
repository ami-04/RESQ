"""Schema validation for single entries and full local log verification.

The verifier mirrors the organiser's finding codes (FORMAT.md section 8) so the
station can audit its own log offline. It is an independent re-implementation
from the spec, not the organiser's server: the server's verdict is authoritative.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from . import crypto

ENTRY_KEYS = ("v", "station_id", "seq", "type", "recorded_at", "payload", "prev_hash", "hash", "sig")
EVENT_TYPES = ("genesis", "checkin", "checkout", "walkin", "rejected", "handover")
ROLES = ("gruen", "gelb", "rot")
ATTEMPTS = ("checkin", "checkout", "walkin")
REASONS = ("unknown_code", "already_checked_in", "not_checked_in", "no_consent", "remote_suspected", "other")
SOURCE_KINDS = ("station", "paper", "phone")

# Codes: XXX-XXX from A-Z without I and O, plus 2-9 (FORMAT.md section 3)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{3}-[A-HJ-NP-Z2-9]{3}$")
WALKIN_RE = re.compile(r"^W-[A-Z0-9]+-\d{4}$")
STATION_ID_RE = re.compile(r"^ST-[A-Z0-9]+$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")


# --------------------------------------------------------------------------- helpers

def parse_time(value) -> datetime | None:
    """Parse a timezone-aware ISO 8601 time with second precision, or None."""
    if not isinstance(value, str) or not TIME_RE.match(value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def forbidden_values(obj, path="") -> list[str]:
    """FORMAT.md section 2: only text, integers, booleans, objects, lists. No floats, no null."""
    problems = []
    if obj is None:
        problems.append(f"{path or '<root>'}: null not allowed")
    elif isinstance(obj, float):
        problems.append(f"{path}: decimal number not allowed")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                problems.append(f"{path}: non-text key")
            problems.extend(forbidden_values(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            problems.extend(forbidden_values(v, f"{path}[{i}]"))
    elif not isinstance(obj, (str, bool, int)):
        problems.append(f"{path}: unsupported type {type(obj).__name__}")
    return problems


def _check_source(payload: dict, errs: list[str]) -> None:
    src = payload.get("source")
    if not isinstance(src, dict):
        errs.append("payload.source missing or not an object")
        return
    kind = src.get("kind")
    if kind not in SOURCE_KINDS:
        errs.append(f"payload.source.kind unknown: {kind!r}")
        return
    if kind == "paper":
        if not isinstance(src.get("sheet"), str) or not src.get("sheet"):
            errs.append("paper source needs text 'sheet'")
        if not _is_int(src.get("line")) or src.get("line") < 1:
            errs.append("paper source needs positive integer 'line'")
        if src.get("confirmed") is not True:
            errs.append("paper source needs confirmed: true")
        occ = payload.get("occurred_at")
        dt = parse_time(occ)
        if dt is None:
            errs.append("paper entry needs readable payload.occurred_at")
        elif dt.second != 0:
            errs.append("occurred_at must be to the minute (seconds :00)")
    elif kind == "phone":
        if not isinstance(src.get("proof"), dict):
            errs.append("phone source needs object 'proof'")
    if kind != "paper" and "occurred_at" in payload:
        errs.append("occurred_at only allowed for paper entries")


def _check_identity(payload: dict, errs: list[str], required: bool) -> None:
    has_code = "code" in payload
    has_w = "walkin_id" in payload
    if has_code and has_w:
        errs.append("payload has both code and walkin_id")
    if required and not (has_code or has_w):
        errs.append("payload needs code or walkin_id")
    if has_code and (not isinstance(payload["code"], str) or not payload["code"]):
        errs.append("code must be non-empty text")
    if has_w and (not isinstance(payload["walkin_id"], str) or not WALKIN_RE.match(payload["walkin_id"])):
        errs.append("walkin_id must match W-<team>-<4 digits>")


def validate_entry_schema(entry) -> list[str]:
    """Return a list of schema problems (empty = OK). Does not check hash/sig/chain."""
    errs: list[str] = []
    if not isinstance(entry, dict):
        return ["entry is not a JSON object"]
    for k in ENTRY_KEYS:
        if k not in entry:
            errs.append(f"missing field {k}")
    extra = set(entry) - set(ENTRY_KEYS)
    if extra:
        errs.append(f"unexpected fields {sorted(extra)}")
    errs.extend(forbidden_values(entry))
    if errs:
        return errs
    if entry["v"] != 1 or not _is_int(entry["v"]):
        errs.append("v must be integer 1")
    if not isinstance(entry["station_id"], str) or not STATION_ID_RE.match(entry["station_id"]):
        errs.append("station_id invalid")
    if not _is_int(entry["seq"]) or entry["seq"] < 1:
        errs.append("seq must be integer >= 1")
    if entry["type"] not in EVENT_TYPES:
        errs.append(f"type unknown: {entry['type']!r}")
    if parse_time(entry["recorded_at"]) is None:
        errs.append("recorded_at not a readable ISO 8601 time with zone and seconds")
    for k in ("prev_hash", "hash"):
        if not isinstance(entry[k], str) or not HEX64_RE.match(entry[k]):
            errs.append(f"{k} must be 64 lowercase hex characters")
    if not isinstance(entry["sig"], str):
        errs.append("sig must be text")
    p = entry["payload"]
    if not isinstance(p, dict):
        errs.append("payload must be an object")
        return errs
    t = entry["type"]
    if t == "genesis":
        for k in ("station_pubkey", "team_id", "app_version"):
            if not isinstance(p.get(k), str) or not p.get(k):
                errs.append(f"genesis needs text {k}")
        try:
            crypto.public_key_from_b64(p.get("station_pubkey", ""))
        except Exception:
            errs.append("genesis station_pubkey is not a 32-byte Base64 key")
    elif t in ("checkin", "checkout"):
        _check_identity(p, errs, required=True)
        _check_source(p, errs)
    elif t == "walkin":
        if not isinstance(p.get("walkin_id"), str) or not WALKIN_RE.match(p.get("walkin_id", "")):
            errs.append("walkin needs walkin_id W-<team>-<4 digits>")
        if not isinstance(p.get("name"), str) or not p.get("name", "").strip():
            errs.append("walkin needs a name")
        if p.get("role_claimed") not in ROLES:
            errs.append("role_claimed must be gruen, gelb or rot")
        if not isinstance(p.get("skill"), str):
            errs.append("skill must be text (may be empty)")
        if p.get("consent") is not True:
            errs.append("walkin requires consent: true")
        if not isinstance(p.get("consent_version"), str) or not p.get("consent_version"):
            errs.append("walkin needs consent_version")
        _check_source(p, errs)
    elif t == "rejected":
        if p.get("attempt") not in ATTEMPTS:
            errs.append("rejected.attempt must be checkin, checkout or walkin")
        if p.get("reason") not in REASONS:
            errs.append(f"rejected.reason unknown: {p.get('reason')!r}")
        if p.get("reason") == "other" and (not isinstance(p.get("note"), str) or not p.get("note")):
            errs.append("reason 'other' needs a text note")
        if p.get("reason") == "no_consent" and "name" in p:
            errs.append("no_consent must not store a name")
        _check_identity(p, errs, required=False)
        _check_source(p, errs)
    elif t == "handover":
        for k in ("last_seq", "count"):
            if not _is_int(p.get(k)):
                errs.append(f"handover needs integer {k}")
        if _is_int(entry["seq"]) and (p.get("last_seq") != entry["seq"] or p.get("count") != entry["seq"]):
            errs.append("handover last_seq and count must equal its own seq")
    return errs


# --------------------------------------------------------------------------- log verification

@dataclass
class Finding:
    code: str
    level: str  # "fehler" | "warnung" | "info" (same words as the server)
    seq: int | None
    detail: str

    def as_dict(self) -> dict:
        d = {"code": self.code, "level": self.level, "detail": self.detail}
        if self.seq is not None:
            d["seq"] = self.seq
        return d


@dataclass
class VerifyReport:
    lines: int = 0
    entries: int = 0
    accepted_up_to: int = 0
    chain_ok: bool = True
    ends_with_handover: bool = False
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "fehler"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {f.code for f in self.findings}

    def as_dict(self) -> dict:
        return {
            "lines": self.lines,
            "entries": self.entries,
            "accepted_up_to": self.accepted_up_to,
            "chain_ok": self.chain_ok,
            "ends_with_handover": self.ends_with_handover,
            "ok": self.ok,
            "findings": [f.as_dict() for f in self.findings],
        }


def verify_log(lines: Iterable, expected_pubkey_b64: str | None = None,
               codes: set[str] | None = None) -> VerifyReport:
    """Verify a JSONL log offline.

    expected_pubkey_b64: the registered key. If None, the key from genesis is used
    (like the server's I_OHNE_SCHLUESSEL mode).
    codes: valid code list for W_LOGIK checks (optional).
    """
    rep = VerifyReport()
    add = rep.findings.append

    def err(code, seq, detail):
        add(Finding(code, "fehler", seq, detail))
        if rep.chain_ok:
            rep.chain_ok = False

    parsed: list[dict] = []
    for idx, raw in enumerate(lines, start=1):
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                rep.lines += 1
                add(Finding("I_KEIN_JSON", "info", None, f"line {idx}: not UTF-8"))
                continue
        raw = raw.strip("\r\n")
        if not raw.strip():
            continue
        rep.lines += 1
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            add(Finding("I_KEIN_JSON", "info", None, f"line {idx}: not JSON (reported, chain not broken)"))
            continue
        parsed.append(obj)
    rep.entries = len(parsed)

    pub = None
    if expected_pubkey_b64:
        pub = crypto.public_key_from_b64(expected_pubkey_b64)
    elif not expected_pubkey_b64:
        add(Finding("I_OHNE_SCHLUESSEL", "info", None, "no registered key given, using key from genesis"))

    known: dict[int, str] = {}        # seq -> hash of accepted/seen entry
    expected_seq = 1
    prev_hash = crypto.GENESIS_PREV_HASH
    station_id = None
    last_valid = None
    first_error_seen = False

    for e in parsed:
        seq = e.get("seq") if isinstance(e, dict) else None
        sseq = seq if _is_int(seq) else None

        # duplicates / conflicts with an already-seen seq
        if sseq is not None and sseq in known:
            if isinstance(e, dict) and e.get("hash") == known[sseq] and crypto.compute_hash(e) == e.get("hash"):
                add(Finding("I_DUPLIKAT", "info", sseq, "entry already known, ignored"))
            else:
                err("E_KONFLIKT", sseq, "same seq, different content")
                first_error_seen = True
            continue

        schema = validate_entry_schema(e)
        if schema:
            err("E_SCHEMA", sseq, "; ".join(schema[:4]))
            first_error_seen = True
            if sseq is not None:
                known[sseq] = e.get("hash") if isinstance(e, dict) else ""
            continue

        if sseq != expected_seq:
            if sseq > expected_seq:
                err("E_LUECKE", sseq, f"expected seq {expected_seq}, got {sseq}")
            first_error_seen = True

        # genesis rules
        if sseq == 1:
            if e["type"] != "genesis":
                err("E_GENESIS", 1, "seq 1 is not genesis")
                first_error_seen = True
            else:
                gpk = e["payload"]["station_pubkey"]
                if pub is None:
                    pub = crypto.public_key_from_b64(gpk)
                elif gpk != expected_pubkey_b64:
                    err("E_GENESIS", 1, "genesis station_pubkey is not the registered key")
                    first_error_seen = True
                station_id = e["station_id"]
        elif e["type"] == "genesis":
            err("E_GENESIS", sseq, "genesis only allowed at seq 1")
            first_error_seen = True

        if station_id is not None and e["station_id"] != station_id:
            err("E_SCHEMA", sseq, "station_id differs from genesis")
            first_error_seen = True

        # hash
        if crypto.compute_hash(e) != e["hash"]:
            err("E_HASH", sseq, "content does not match hash")
            first_error_seen = True
        elif pub is None or not crypto.verify_signature(pub, e["hash"], e["sig"]):
            err("E_SIGNATUR", sseq, "signature does not match key")
            first_error_seen = True

        if e["prev_hash"] != prev_hash:
            err("E_KETTE", sseq, "prev_hash does not match previous entry")
            first_error_seen = True

        known[sseq] = e["hash"]
        prev_hash = e["hash"]
        expected_seq = sseq + 1
        last_valid = e
        if not first_error_seen:
            rep.accepted_up_to = sseq

    if last_valid is None or last_valid.get("type") != "handover":
        add(Finding("W_ENDE", "warnung", last_valid.get("seq") if last_valid else None,
                    "last entry is not a handover"))
    else:
        rep.ends_with_handover = True

    # logic warnings over the accepted part
    accepted = [e for e in parsed if isinstance(e, dict) and _is_int(e.get("seq"))
                and e.get("seq", 0) <= rep.accepted_up_to]
    seen = set()
    for f in logic_findings(accepted, codes):
        key = (f.seq, f.detail)
        if key not in seen:
            seen.add(key)
            add(f)
    return rep


def logic_findings(entries: list[dict], codes: set[str] | None) -> list[Finding]:
    """W_LOGIK: contradictions inside a valid chain."""
    out: list[Finding] = []
    active: set[tuple[str, str]] = set()
    walkins: set[str] = set()
    seen_seq: set[int] = set()
    for e in sorted(entries, key=lambda x: x["seq"]):
        if e["seq"] in seen_seq:
            continue
        seen_seq.add(e["seq"])
        t, p, s = e["type"], e["payload"], e["seq"]
        if t == "walkin":
            w = p["walkin_id"]
            if w in walkins:
                out.append(Finding("W_LOGIK", "warnung", s, f"walkin_id {w} assigned twice"))
            walkins.add(w)
            active.add(("walkin_id", w))
        elif t in ("checkin", "checkout"):
            if "code" in p:
                key = ("code", p["code"])
                if codes is not None and p["code"] not in codes:
                    out.append(Finding("W_LOGIK", "warnung", s, f"code {p['code']} not on code list"))
            else:
                key = ("walkin_id", p["walkin_id"])
                if p["walkin_id"] not in walkins:
                    out.append(Finding("W_LOGIK", "warnung", s, f"walkin_id {p['walkin_id']} never registered"))
            if t == "checkin":
                if key in active:
                    out.append(Finding("W_LOGIK", "warnung", s, "check-in while already checked in"))
                active.add(key)
            else:
                if key not in active:
                    out.append(Finding("W_LOGIK", "warnung", s, "check-out without check-in"))
                active.discard(key)
    return out


def b64_ok(s: str) -> bool:
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False
