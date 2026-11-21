"""English / German screen texts stay complete and in sync.

The signed log is never translated: only the screen is. These tests make sure that
(1) every text key exists in both languages, (2) every key used in the pages and scripts
exists, and (3) every message the station app can send has a German translation.
"""
import re
from pathlib import Path

import pytest

from backend import paper, phone
from backend import registration as reg
from backend.routes import readiness
from backend.sync import STATUS_TEXT, ApiClient

ROOT = Path(__file__).resolve().parents[1]
I18N = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")


def _keys(block: str) -> set[str]:
    return set(re.findall(r'"([a-z][a-z0-9._]*)":', block))


EN_BLOCK = I18N.split("\n  en: {", 1)[1].split("\n  de: {", 1)[0]
DE_BLOCK = I18N.split("\n  de: {", 1)[1].split("\n};", 1)[0]
EN, DE = _keys(EN_BLOCK), _keys(DE_BLOCK)

# JS regex literals of the server-message table -> Python regexes (same syntax for what we use)
_TABLE = I18N.split("const SERVER_DE = [", 1)[1].split("\n];", 1)[0]
SERVER_PATTERNS = [re.compile(p.replace(r"\/", "/")) for p in re.findall(r"^\s*\[/(.+?)/, \"", _TABLE, re.M)]
READY_DE = set(re.findall(r'"([A-Z][^"]+)": "', I18N.split("const READY_DE = {", 1)[1].split("};", 1)[0]))


def translated(msg: str) -> bool:
    return any(p.search(msg) for p in SERVER_PATTERNS)


def test_both_languages_have_the_same_keys():
    assert EN and EN == DE, f"only EN: {sorted(EN - DE)} · only DE: {sorted(DE - EN)}"


def test_every_key_used_in_pages_and_scripts_exists():
    used = set()
    for tpl in ("index.html", "phone.html"):
        html = (ROOT / "templates" / tpl).read_text(encoding="utf-8")
        used |= set(re.findall(r'data-i18n(?:-html|-ph)?="([^"]+)"', html))
    for js in ("app.js", "phone.js"):
        src = (ROOT / "static" / js).read_text(encoding="utf-8")
        used |= set(re.findall(r'\btr\("([a-z][a-z0-9._]*)"', src))
        used |= set(re.findall(r'idle\([^,]+, "([a-z][a-z0-9._]*)"', src))
    used = {k for k in used if not k.endswith(".")}          # prefixes built at runtime, e.g. tr("tag." + status)
    used |= {f"tag.{s}" for s in ("success", "rejected", "invalid", "error")}
    assert used - EN == set()


def test_station_messages_all_have_german(station):
    msgs = []
    add = lambda out: msgs.append(out.message)  # noqa: E731
    add(reg.checkin(station, "??"))
    add(reg.checkin(station, "X3K-9PZ"))
    add(reg.checkin(station, "W-T9-0999"))
    add(reg.checkin(station, "3NW-4UJ"))
    add(reg.checkin(station, "3NW-4UJ"))
    add(reg.checkout(station, "84M-6GV"))
    add(reg.checkout(station, "3NW-4UJ"))
    add(reg.walkin(station, name="", role="gelb", skill="", consent=True))
    add(reg.walkin(station, name="A", role="", skill="", consent=True))
    add(reg.walkin(station, name="A", role="gelb", skill="", consent=True))
    add(reg.walkin(station, name="A", role="gelb", skill="", consent=False))
    today = station.now_dt().strftime("%Y-%m-%d")
    base = dict(sheet="P-T9-01", line=1, event_type="checkin", confirmed=True, date=today, time="00:00",
                identifier="9MF-SVJ", name="", role="", skill="", consent=False)
    add(paper.import_line(station, **{**base, "confirmed": False}))
    add(paper.import_line(station, **{**base, "sheet": ""}))
    add(paper.import_line(station, **{**base, "line": ""}))
    add(paper.import_line(station, **{**base, "line": 0}))
    add(paper.import_line(station, **{**base, "event_type": "x"}))
    add(paper.import_line(station, **{**base, "time": "99"}))
    add(paper.import_line(station, **{**base, "date": "2999-01-01"}))
    add(paper.import_line(station, **base))
    add(paper.import_line(station, **base))
    board = phone.ChallengeBoard()
    ch = board.current()["challenge"]
    add(phone.phone_checkin(station, board, "", ch))
    add(phone.phone_checkin(station, board, "ACZ-GXK", ""))
    add(phone.phone_checkin(station, board, "ACZ-GXK", "ZZZZ"))
    add(phone.phone_checkin(station, board, "ACZ-GXK", ch))
    assert reg.checkout(station, "ACZ-GXK").status == "success"
    add(phone.phone_checkin(station, board, "ACZ-GXK", ch))
    missing = [m for m in msgs if not translated(m)]
    assert len(msgs) >= 25 and missing == []


def test_readiness_names_and_details_have_german(station):
    api = ApiClient("https://example.invalid", None)
    for check in readiness(station, api, probe_api=False):
        assert check["name"] in READY_DE
        assert translated(check["detail"]) or check["detail"].startswith("/"), check["detail"]


@pytest.mark.parametrize("status", sorted(STATUS_TEXT))
def test_server_status_texts_have_german(status):
    assert translated(STATUS_TEXT[status]) and translated(STATUS_TEXT[status] + ": detail from server")


def test_sync_error_texts_have_german():
    src = (ROOT / "backend" / "sync.py").read_text(encoding="utf-8")
    for msg in ("Server not reachable (ConnectionError). Offline? Your data is safe locally; retry later.",
                "RESQ_TEAM_TOKEN is not set (see README: token configuration)", "RESQ_TEAM_TOKEN is not set.",
                "Local verification found errors; not uploading. See findings.", "Upload body would exceed 5 MB",
                "This is a REHEARSAL data directory. Uploading it is blocked to protect the competition log. "
                "Use the live data directory."):
        assert msg.split(" (")[0].split(".")[0][:25] in src.replace('"\n', "").replace('                     "', "")
        assert translated(msg), msg
