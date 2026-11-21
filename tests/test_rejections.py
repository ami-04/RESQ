"""The five station attacks (FORMAT.md section 10) and other refusals."""
import pytest

from backend import registration as reg
from backend.validation import verify_log


def _last(st):
    return st.log.entries[-1]


def _chain_ok(st):
    rep = verify_log(st.log.lines(), expected_pubkey_b64=st.keys.public_key_b64(), codes=set(st.codes))
    assert rep.ok, rep.as_dict()
    # no W_LOGIK: an attack never slipped through as a valid entry
    assert "W_LOGIK" not in rep.codes(), rep.as_dict()


def test_attack_made_up_code(station):
    out = reg.checkin(station, "X3K-9PZ")
    assert out.status == "rejected" and out.reason == "unknown_code"
    assert _last(station)["payload"] == {"attempt": "checkin", "reason": "unknown_code", "code": "X3K-9PZ",
                                         "source": {"kind": "station"}}
    assert not station.state.active
    _chain_ok(station)


def test_attack_made_up_code_logs_exact_code_given(station):
    # A code with I/O is not even in the alphabet: still logged exactly as given (upper-cased).
    out = reg.checkin(station, "ABI-OO1")
    assert out.reason == "unknown_code"
    assert _last(station)["payload"]["code"] == "ABI-OO1"


def test_attack_double_checkin(station):
    reg.checkin(station, "3NW-4UJ")
    out = reg.checkin(station, "3NW-4UJ")
    assert out.status == "rejected" and out.reason == "already_checked_in"
    assert _last(station)["payload"] == {"attempt": "checkin", "reason": "already_checked_in",
                                         "code": "3NW-4UJ", "source": {"kind": "station"}}
    assert station.state.counts["checkin"] == 1
    _chain_ok(station)


def test_attack_checkout_without_checkin(station):
    out = reg.checkout(station, "9MF-SVJ")
    assert out.status == "rejected" and out.reason == "not_checked_in"
    assert _last(station)["payload"] == {"attempt": "checkout", "reason": "not_checked_in",
                                         "code": "9MF-SVJ", "source": {"kind": "station"}}
    assert station.state.counts["checkout"] == 0
    _chain_ok(station)


def test_attack_no_consent_stores_no_name(station):
    out = reg.walkin(station, name="Secret Person", role="gelb", skill="Koch", consent=False)
    assert out.status == "rejected" and out.reason == "no_consent"
    p = _last(station)["payload"]
    assert p == {"attempt": "walkin", "reason": "no_consent", "source": {"kind": "station"}}
    assert b"Secret Person" not in station.cfg.log_path.read_bytes()
    assert b"Koch" not in station.cfg.log_path.read_bytes()
    assert not station.state.walkins
    _chain_ok(station)


def test_no_consent_does_not_consume_walkin_id(station):
    reg.walkin(station, name="X", role="gelb", skill="", consent=False)
    out = reg.walkin(station, name="Y", role="gelb", skill="", consent=True)
    assert out.extra["walkin_id"] == "W-T9-0001"


def test_checkout_of_unknown_code(station):
    out = reg.checkout(station, "ZZZ-ZZZ")
    assert out.reason == "unknown_code"
    assert _last(station)["payload"]["attempt"] == "checkout"
    _chain_ok(station)


@pytest.mark.parametrize("fn", [reg.checkin, reg.checkout])
def test_unissued_walkin_id_rejected_as_other_with_note(station, fn):
    out = fn(station, "W-T9-0042")
    assert out.status == "rejected" and out.reason == "other"
    p = _last(station)["payload"]
    assert "walkin_id" not in p and "W-T9-0042" in p["note"]
    _chain_ok(station)


def test_double_checkin_of_walkin(station):
    reg.walkin(station, name="A", role="gruen", skill="", consent=True)
    out = reg.checkin(station, "W-T9-0001")
    assert out.reason == "already_checked_in"
    assert _last(station)["payload"]["walkin_id"] == "W-T9-0001"
    _chain_ok(station)


@pytest.mark.parametrize("bad", ["", "   ", "HELLO", "12", None, "ABCD-EFGH", "W-T9-12"])
def test_malformed_input_writes_nothing(station, bad):
    n = len(station.log)
    assert reg.checkin(station, bad).status == "invalid"
    assert reg.checkout(station, bad).status == "invalid"
    assert len(station.log) == n


def test_rejections_counted_by_reason(station):
    reg.checkin(station, "X3K-9PZ")
    reg.checkout(station, "9MF-SVJ")
    reg.walkin(station, name="", role="", skill="", consent=False)
    assert station.state.rejected_by_reason == {"unknown_code": 1, "not_checked_in": 1, "no_consent": 1}
