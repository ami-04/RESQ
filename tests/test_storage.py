"""Persistence, crash recovery, concurrency and key protection."""
import threading

import pytest

from backend import crypto
from backend import registration as reg
from backend.station import SetupError, Station
from backend.storage import KeyStore, LockError, StorageError
from backend.validation import verify_log
from tests.conftest import reopen


def test_restart_without_data_loss(station):
    reg.checkin(station, "3NW-4UJ")
    reg.walkin(station, name="A", role="gruen", skill="", consent=True)
    before = list(station.log.entries)
    st2 = reopen(station)
    try:
        assert st2.log.entries == before
        assert st2.log.next_seq() == 4
        assert st2.state.is_active(("code", "3NW-4UJ")) and st2.state.is_active(("walkin_id", "W-T9-0001"))
        assert reg.checkin(st2, "3NW-4UJ").reason == "already_checked_in"
        assert reg.walkin(st2, name="B", role="gruen", skill="", consent=True).extra["walkin_id"] == "W-T9-0002"
        assert st2.log.entries[-1]["seq"] == 5
    finally:
        st2.close()


def test_file_uses_lf_and_utf8(station):
    reg.walkin(station, name="Jörg", role="gruen", skill="", consent=True)
    raw = station.cfg.log_path.read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    assert "Jörg".encode("utf-8") in raw


def test_torn_last_line_is_recovered(station):
    reg.checkin(station, "3NW-4UJ")
    good = station.cfg.log_path.read_bytes()
    with open(station.cfg.log_path, "ab") as fh:
        fh.write(b'{"v":1,"station_id":"ST-T9","seq":3,"ty')  # power cut mid-write
    st2 = reopen(station)
    try:
        assert st2.log.corruption is None
        assert st2.cfg.log_path.read_bytes() == good
        assert st2.log.recovered_fragment and st2.log.recovered_fragment.exists()
        assert reg.checkout(st2, "3NW-4UJ").status == "success"
        rep = verify_log(st2.log.lines(), expected_pubkey_b64=st2.keys.public_key_b64())
        assert rep.ok
    finally:
        st2.close()


def test_corrupt_middle_line_blocks_writes(station):
    reg.checkin(station, "3NW-4UJ")
    reg.checkout(station, "3NW-4UJ")
    lines = station.cfg.log_path.read_bytes().split(b"\n")
    lines[1] = b"garbage"
    station.cfg.log_path.write_bytes(b"\n".join(lines))
    st2 = reopen(station)
    try:
        assert st2.log.corruption
        with pytest.raises(StorageError):
            reg.checkin(st2, "84M-6GV")
    finally:
        st2.close()


def test_concurrent_writes_get_unique_gapless_seqs(station):
    codes = list(station.codes)
    errors = []

    def worker(code):
        try:
            reg.checkin(station, code)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(c,)) for c in codes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    seqs = [e["seq"] for e in station.log.entries]
    assert seqs == list(range(1, len(codes) + 2))
    rep = verify_log(station.log.lines(), expected_pubkey_b64=station.keys.public_key_b64())
    assert rep.ok


def test_second_process_cannot_open_same_data_dir(station):
    with pytest.raises(LockError):
        Station.open(station.cfg)


def test_genesis_cannot_be_rewritten(station):
    with pytest.raises(SetupError):
        station.initialise("ST-T9")


def test_key_is_never_overwritten(cfg):
    ks = KeyStore(cfg.key_path)
    ks.save_new(crypto.generate_private_key())
    with pytest.raises(StorageError):
        ks.save_new(crypto.generate_private_key())


def test_public_test_key_is_refused(cfg, t1_key):
    test_key = crypto.private_key_from_seed(bytes.fromhex(t1_key["seed_hex"]))
    with pytest.raises(StorageError):
        KeyStore(cfg.key_path).save_new(test_key)


def test_history_not_modified_by_appends(station):
    reg.checkin(station, "3NW-4UJ")
    snapshot = station.cfg.log_path.read_bytes()
    reg.checkout(station, "3NW-4UJ")
    assert station.cfg.log_path.read_bytes().startswith(snapshot)


def test_writes_refused_before_genesis(cfg):
    KeyStore(cfg.key_path).save_new(crypto.generate_private_key())
    st = Station.open(cfg)
    try:
        with pytest.raises(SetupError):
            reg.checkin(st, "3NW-4UJ")
    finally:
        st.close()


def test_genesis_requires_key(cfg):
    st = Station.open(cfg)
    try:
        with pytest.raises(SetupError):
            st.initialise("ST-T9")
    finally:
        st.close()


def test_invalid_station_id_refused(cfg):
    KeyStore(cfg.key_path).save_new(crypto.generate_private_key())
    st = Station.open(cfg)
    try:
        with pytest.raises(SetupError):
            st.initialise("T9")
    finally:
        st.close()
