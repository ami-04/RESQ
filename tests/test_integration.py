"""End-to-end scenario from the brief, including restart, handover and (mocked) upload."""
import json

from backend import paper
from backend import registration as reg
from backend.sync import ApiClient, SyncState, upload
from backend.validation import verify_log
from tests.conftest import reopen
from tests.test_sync import FakeResp, FakeSession, ok_body


def test_full_station_day(station):
    st = station
    # 1-3: valid check-in, duplicate rejected, check-out
    assert reg.checkin(st, "3NW-4UJ").ok
    assert reg.checkin(st, "3NW-4UJ").reason == "already_checked_in"
    assert reg.checkout(st, "3NW-4UJ").ok
    # 4-5: walk-in with and without consent
    w = reg.walkin(st, name="Lena Beispiel", role="gelb", skill="Pflegefachkraft", consent=True)
    assert w.ok
    reg.walkin(st, name="Should Not Be Stored", role="gruen", skill="", consent=False)
    assert b"Should Not Be Stored" not in st.cfg.log_path.read_bytes()
    # remaining attacks
    reg.checkin(st, "X3K-9PZ")
    reg.checkout(st, "9MF-SVJ")
    # 6: confirmed paper entry
    assert paper.import_line(st, sheet="P-T9-01", line=3, event_type="walkin", confirmed=True,
                             date=st.now_dt().strftime("%Y-%m-%d"), time="00:00",
                             name="Tom Muster", role="gruen", skill="", consent=True).ok
    n_before = len(st.log)
    # 7: restart
    st2 = reopen(st)
    try:
        assert len(st2.log) == n_before
        assert set(st2.state.active) == {("walkin_id", "W-T9-0001"), ("walkin_id", "W-T9-0002")}
        assert st2.state.rejected_by_reason == {"already_checked_in": 1, "no_consent": 1,
                                                "unknown_code": 1, "not_checked_in": 1}
        # 8: still valid after restart
        assert verify_log(st2.log.lines(), expected_pubkey_b64=st2.keys.public_key_b64()).ok
        assert reg.checkout(st2, w.extra["walkin_id"]).ok
        # 9-11: connection restored -> handover + upload (mocked server)
        session = FakeSession([FakeResp(200, ok_body(n_before + 2))])
        api = ApiClient("https://example.invalid", "tok", session=session, sleep=lambda _: None)
        res = upload(st2, api)
        sent = [json.loads(l) for l in session.calls[0]["data"].decode().splitlines()]
        assert sent[-1]["type"] == "handover"
        assert sent[-1]["payload"] == {"last_seq": len(sent), "count": len(sent)}
        assert [e["seq"] for e in sent] == list(range(1, len(sent) + 1))
        rep = verify_log(session.calls[0]["data"].split(b"\n"), expected_pubkey_b64=st2.keys.public_key_b64(),
                         codes=set(st2.codes))
        assert rep.ok and rep.ends_with_handover and rep.accepted_up_to == len(sent)
        assert "W_LOGIK" not in rep.codes()
        assert SyncState(st2.cfg.sync_path).accepted_up_to == res["response"]["accepted_up_to"]
        # the five official attacks (four without phone) are all in the uploaded log
        rej = {(e["payload"]["attempt"], e["payload"]["reason"]) for e in sent if e["type"] == "rejected"}
        assert {("checkin", "unknown_code"), ("checkin", "already_checked_in"),
                ("checkout", "not_checked_in"), ("walkin", "no_consent")} <= rej
    finally:
        st2.close()
