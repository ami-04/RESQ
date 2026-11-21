"""Manipulation of a COPY of the log must be detected by the local verifier
(mirrors what the organiser's verification server checks, FORMAT.md section 8/10)."""
import json

import pytest

from backend import crypto
from backend import registration as reg
from backend.sync import ensure_handover
from backend.validation import verify_log


@pytest.fixture
def sealed_log(station):
    reg.checkin(station, "3NW-4UJ")
    reg.walkin(station, name="Lena", role="gelb", skill="Pflege", consent=True)
    reg.checkin(station, "X3K-9PZ")
    reg.checkout(station, "3NW-4UJ")
    reg.checkin(station, "84M-6GV")
    ensure_handover(station)
    lines = [json.loads(l) for l in station.log.lines()]
    return station, lines


def _verify(st, entries):
    raw = [json.dumps(e, ensure_ascii=False).encode("utf-8") for e in entries]
    return verify_log(raw, expected_pubkey_b64=st.keys.public_key_b64(), codes=set(st.codes))


def test_untouched_copy_is_clean(sealed_log):
    st, entries = sealed_log
    rep = _verify(st, entries)
    assert rep.ok and rep.ends_with_handover and rep.accepted_up_to == len(entries)
    assert not [f for f in rep.findings if f.level != "info"]


def test_changed_field_without_new_hash(sealed_log):
    st, e = sealed_log
    e[2]["payload"]["name"] = "Mallory"
    rep = _verify(st, e)
    assert "E_HASH" in rep.codes() and rep.accepted_up_to == 2


def test_changed_field_with_recomputed_hash(sealed_log):
    st, e = sealed_log
    e[2]["payload"]["name"] = "Mallory"
    e[2]["hash"] = crypto.compute_hash(e[2])
    rep = _verify(st, e)
    assert "E_SIGNATUR" in rep.codes()
    assert "E_KETTE" in rep.codes()  # next entry's prev_hash no longer matches


def test_changed_field_resigned_with_other_key(sealed_log):
    st, e = sealed_log
    e[2]["payload"]["name"] = "Mallory"
    e[2] = crypto.seal(e[2], crypto.generate_private_key())
    assert "E_SIGNATUR" in _verify(st, e).codes()


def test_deleted_middle_event(sealed_log):
    st, e = sealed_log
    del e[3]
    rep = _verify(st, e)
    assert {"E_LUECKE", "E_KETTE"} <= rep.codes() and rep.accepted_up_to == 3


def test_inserted_fake_event_with_existing_seq(sealed_log):
    st, e = sealed_log
    fake = dict(e[1], payload={"code": "84M-6GV", "source": {"kind": "station"}})
    fake["hash"] = crypto.compute_hash(fake)
    e.insert(2, fake)
    assert "E_KONFLIKT" in _verify(st, e).codes()


def test_inserted_and_renumbered_event(sealed_log):
    st, e = sealed_log
    fake = dict(e[1], payload={"code": "84M-6GV", "source": {"kind": "station"}}, seq=3, prev_hash=e[1]["hash"])
    fake["hash"] = crypto.compute_hash(fake)
    rest = []
    for x in e[2:]:
        y = dict(x, seq=x["seq"] + 1)
        rest.append(y)
    rep = _verify(st, e[:2] + [fake] + rest)
    assert rep.codes() & {"E_SIGNATUR", "E_HASH", "E_KETTE"}


def test_duplicated_entry_is_reported(sealed_log):
    st, e = sealed_log
    e.insert(4, dict(e[3]))
    rep = _verify(st, e)
    assert "I_DUPLIKAT" in rep.codes()


def test_truncated_end(sealed_log):
    st, e = sealed_log
    rep = _verify(st, e[:-2])
    assert "W_ENDE" in rep.codes() and not rep.ends_with_handover


def test_wrong_genesis_key(sealed_log):
    st, e = sealed_log
    other = crypto.public_key_b64(crypto.generate_private_key())
    raw = [json.dumps(x).encode() for x in e]
    rep = verify_log(raw, expected_pubkey_b64=other)
    assert "E_GENESIS" in rep.codes()


def test_non_json_line_reported_but_chain_continues(sealed_log):
    st, e = sealed_log
    raw = [json.dumps(x).encode() for x in e]
    raw.insert(3, b"this is not json")
    rep = verify_log(raw, expected_pubkey_b64=st.keys.public_key_b64())
    assert "I_KEIN_JSON" in rep.codes() and rep.ok and rep.accepted_up_to == len(e)


def test_float_and_null_values_are_schema_errors(sealed_log):
    st, e = sealed_log
    e[1]["payload"]["x"] = None
    e[1] = crypto.seal(e[1], st._private_key)
    assert "E_SCHEMA" in _verify(st, e).codes()
