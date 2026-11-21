"""Paper recovery: digitise confirmed lines from the paper backup sheet.

Rules (FORMAT.md sections 3 and 4):
- source = {"kind":"paper","sheet":..,"line":..,"confirmed":true}, payload gets occurred_at
- occurred_at: written by a human on paper, minute precision, seconds always :00
- recorded_at: set by the device at the moment the operator confirms
- unconfirmed lines are never written; photos and signatures are never stored
- the same sheet+line can only be imported once (prevents accidental double import)
The same station rules apply as for live registration, so an unknown code on paper
becomes a signed `rejected` entry with source paper (it is not silently accepted).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from . import registration as reg
from .registration import Outcome

if TYPE_CHECKING:  # pragma: no cover
    from .station import Station

SHEET_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")
PAPER_TYPES = ("checkin", "checkout", "walkin")


def build_occurred_at(st: "Station", date_str: str, time_str: str) -> tuple[str | None, str | None]:
    """Combine a date (YYYY-MM-DD) and clock time (HH:MM) in the station time zone."""
    try:
        d = datetime.strptime((date_str or "").strip(), "%Y-%m-%d")
        t = datetime.strptime((time_str or "").strip()[:5], "%H:%M")
    except ValueError:
        return None, "Enter the date as YYYY-MM-DD and the time as HH:MM (24 h)."
    dt = datetime(d.year, d.month, d.day, t.hour, t.minute, 0, tzinfo=st.tz)
    if dt > st.now_dt() + timedelta(minutes=1):
        return None, "The time on the paper line is in the future. Please check it."
    return dt.isoformat(), None


def import_line(st: "Station", *, sheet, line, event_type, confirmed, date, time,
                identifier=None, name=None, role=None, skill=None, consent=None) -> Outcome:
    if confirmed is not True:
        return Outcome("invalid", "Not imported: the operator must confirm the paper line first.")
    sheet_n = (sheet or "").strip().upper().replace(" ", "")
    if not SHEET_RE.match(sheet_n):
        return Outcome("invalid", "Enter the sheet ID printed on the paper (e.g. P-T1-02).")
    try:
        line_n = int(str(line).strip())
    except (TypeError, ValueError):
        return Outcome("invalid", "Enter the line number (1, 2, 3 ...).")
    if not 1 <= line_n <= 9999:
        return Outcome("invalid", "Line number must be between 1 and 9999.")
    if event_type not in PAPER_TYPES:
        return Outcome("invalid", "Choose check-in, check-out or walk-in.")
    occurred_at, problem = build_occurred_at(st, date, time)
    if problem:
        return Outcome("invalid", problem)

    source = {"kind": "paper", "sheet": sheet_n, "line": line_n, "confirmed": True}
    with st.write_lock:
        if (sheet_n, line_n) in st.state.paper_keys:
            return Outcome("invalid", f"Sheet {sheet_n} line {line_n} was already imported. Nothing recorded.",
                           extra={"duplicate": True})
        if event_type == "checkin":
            out = reg.checkin(st, identifier, source=source, occurred_at=occurred_at)
        elif event_type == "checkout":
            out = reg.checkout(st, identifier, source=source, occurred_at=occurred_at)
        else:
            out = reg.walkin(st, name=name, role=role, skill=skill, consent=consent is True,
                             source=source, occurred_at=occurred_at)
    if out.entry:
        out.extra.update({"sheet": sheet_n, "line": line_n, "occurred_at": occurred_at})
    return out
