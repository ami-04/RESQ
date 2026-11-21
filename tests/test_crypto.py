"""Cryptography: canonical JSON, SHA-256, Ed25519 and the OFFICIAL T1 test vectors."""
import base64
import hashlib
import json

import pytest

from backend import crypto
from backend.validation import verify_log
from tests.conftest import TESTFAELLE


def _t1_entries():
    return [json.loads(l) for l in (TESTFAELLE / "T1_gueltig.jsonl").read_text(encoding="utf-8").splitlines() if l]


def test_official_t1_hashes_match_character_for_character():
    expected = json.loads((TESTFAELLE / "T1_erwartet.json").read_text(encoding="utf-8"))["hashes"]
    entries = _t1_entries()
    assert len(entries) == len(expected) == 11
    for e, h in zip(entries, expected):
        assert crypto.compute_hash(e) == h


def test_official_t1_signatures_reproduced_with_test_key(t1_key):
    key = crypto.private_key_from_seed(bytes.fromhex(t1_key["seed_hex"]))
    assert crypto.public_key_b64(key) == t1_key["public_key_b64"]
    for e in _t1_entries():
        sealed = crypto.seal(e, key)
        assert sealed["hash"] == e["hash"]
        assert sealed["sig"] == e["sig"]  # Ed25519 is deterministic


def test_official_t1_log_verifies_locally(t1_lines, t1_key):
    rep = verify_log(t1_lines, expected_pubkey_b64=t1_key["public_key_b64"])
    assert rep.ok, rep.as_dict()
    assert rep.accepted_up_to == 11
    assert rep.ends_with_handover


def test_canonical_sorts_nested_keys_and_removes_whitespace():
    assert crypto.canonical({"b": 1, "a": {"z": 1, "y": [{"d": 1, "c": 2}]}}) == \
        b'{"a":{"y":[{"c":2,"d":1}],"z":1},"b":1}'


def test_canonical_keeps_non_ascii_unescaped_utf8():
    out = crypto.canonical({"skill": "Notfallsanitäterin"})
    assert out == '{"skill":"Notfallsanitäterin"}'.encode("utf-8")
    assert b"\\u" not in out


def test_hash_excludes_hash_and_sig():
    e = {"a": 1, "hash": "x", "sig": "y"}
    assert crypto.compute_hash(e) == hashlib.sha256(b'{"a":1}').hexdigest()


def test_signature_is_over_raw_32_digest_bytes():
    key = crypto.generate_private_key()
    h = hashlib.sha256(b"x").hexdigest()
    sig = base64.b64decode(crypto.sign_hash(key, h))
    key.public_key().verify(sig, bytes.fromhex(h))  # raw bytes, not hex text
    with pytest.raises(Exception):
        key.public_key().verify(sig, h.encode())


def test_verify_signature_detects_wrong_key_and_broken_sig():
    k1, k2 = crypto.generate_private_key(), crypto.generate_private_key()
    h = hashlib.sha256(b"x").hexdigest()
    s = crypto.sign_hash(k1, h)
    assert crypto.verify_signature(k1.public_key(), h, s)
    assert not crypto.verify_signature(k2.public_key(), h, s)
    broken = base64.b64encode(bytes(64)).decode()
    assert not crypto.verify_signature(k1.public_key(), h, broken)
    assert not crypto.verify_signature(k1.public_key(), h, "not base64!!")


def test_genesis_prev_hash_is_64_zeros():
    assert crypto.GENESIS_PREV_HASH == "0" * 64
    assert _t1_entries()[0]["prev_hash"] == crypto.GENESIS_PREV_HASH


def test_station_genesis_is_correct(station):
    g = station.log.entries[0]
    assert g["seq"] == 1 and g["type"] == "genesis"
    assert g["prev_hash"] == "0" * 64
    assert g["payload"]["station_pubkey"] == station.keys.public_key_b64()
    assert g["payload"]["team_id"] == "T9"
    assert set(g["payload"]) == {"station_pubkey", "team_id", "app_version"}
    rep = verify_log(station.log.lines(), expected_pubkey_b64=station.keys.public_key_b64())
    assert rep.ok


def test_station_writes_hash_and_sig_like_reference(station):
    from backend import registration as reg
    reg.checkin(station, "3NW-4UJ")
    e = station.log.entries[-1]
    ref = {k: v for k, v in e.items() if k not in ("hash", "sig")}
    ref_hash = hashlib.sha256(json.dumps(ref, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    assert e["hash"] == ref_hash
    assert crypto.verify_signature(crypto.public_key_from_b64(station.keys.public_key_b64()), e["hash"], e["sig"])
