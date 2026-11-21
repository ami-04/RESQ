"""Paper recovery import."""
from datetime import timedelta

from backend import paper
from backend.validation import parse_time, verify_log


def _imp(st, **kw):
    base = dict(sheet="P-T9-02", line=7, event_type="checkin", confirmed=True,
                date=st.now_dt().strftime("%Y-%m-%d"), time="00:00", identifier="3NW-4UJ")
    base.update(kw)
    return paper.import_line(st, **base)


def test_confirmed_paper_checkin(station):
    out = _imp(station)
    assert out.status == "success"
    e = station.log.entries[-1]
    p = e["payload"]
    assert p["source"] == {"kind": "paper", "sheet": "P-T9-02", "line": 7, "confirmed": True}
    assert p["code"] == "3NW-4UJ"
    occ = parse_time(p["occurred_at"])
    assert occ.second == 0 and occ.hour == 0 and occ.minute == 0
    assert parse_time(e["recorded_at"]) is not None


def test_unconfirmed_paper_entry_is_not_written(station):
    n = len(station.log)
    assert _imp(station, confirmed=False).status == "invalid"
    assert _imp(station, confirmed="yes").status == "invalid"
    assert len(station.log) == n


def test_duplicate_sheet_line_refused(station):
    assert _imp(station).status == "success"
    n = len(station.log)
    out = _imp(station, event_type="checkout")
    assert out.status == "invalid" and out.extra.get("duplicate")
    assert len(station.log) == n


def test_duplicate_detection_survives_restart(station):
    from tests.conftest import reopen
    _imp(station)
    st2 = reopen(station)
    try:
        assert _imp(st2).status == "invalid"
    finally:
        st2.close()


def test_occurred_vs_recorded_time(station):
    _imp(station, time="00:01")
    e = station.log.entries[-1]
    occ, rec = parse_time(e["payload"]["occurred_at"]), parse_time(e["recorded_at"])
    assert occ < rec
    assert occ.second == 0 and rec.tzinfo is not None


def test_future_time_refused(station):
    future = station.now_dt() + timedelta(hours=2)
    out = _imp(station, date=future.strftime("%Y-%m-%d"), time=future.strftime("%H:%M"))
    assert out.status == "invalid"


def test_bad_time_format_refused(station):
    assert _imp(station, time="9 Uhr").status == "invalid"
    assert _imp(station, date="21.11.2026").status == "invalid"


def test_paper_walkin_gets_station_id_and_consent(station):
    out = _imp(station, event_type="walkin", identifier=None, name="Tom Muster", role="gruen", skill="",
               consent=True, line=3)
    assert out.status == "success"
    p = station.log.entries[-1]["payload"]
    assert p["walkin_id"] == "W-T9-0001" and p["consent"] is True and p["source"]["kind"] == "paper"
    assert "occurred_at" in p


def test_paper_walkin_without_consent_is_rejected_without_name(station):
    out = _imp(station, event_type="walkin", identifier=None, name="Hidden", role="gruen", consent=False)
    assert out.reason == "no_consent"
    p = station.log.entries[-1]["payload"]
    assert "name" not in p and p["source"]["kind"] == "paper" and "occurred_at" in p


def test_paper_unknown_code_becomes_rejected(station):
    out = _imp(station, identifier="X3K-9PZ")
    assert out.status == "rejected" and out.reason == "unknown_code"
    assert station.log.entries[-1]["payload"]["source"]["kind"] == "paper"


def test_paper_entries_in_same_chain(station):
    from backend import registration as reg
    reg.checkin(station, "84M-6GV")
    _imp(station)
    reg.checkout(station, "84M-6GV")
    rep = verify_log(station.log.lines(), expected_pubkey_b64=station.keys.public_key_b64(), codes=set(station.codes))
    assert rep.ok and rep.accepted_up_to == 4


def test_sheet_normalised(station):
    _imp(station, sheet=" p-t9-05 ")
    assert station.log.entries[-1]["payload"]["source"]["sheet"] == "P-T9-05"
    assert _imp(station, sheet="bad sheet!").status == "invalid"
