"""Check-in, check-out and walk-in workflows."""
from backend import registration as reg
from backend.validation import validate_entry_schema, verify_log


def _verify(st):
    rep = verify_log(st.log.lines(), expected_pubkey_b64=st.keys.public_key_b64(), codes=set(st.codes))
    assert rep.ok, rep.as_dict()
    return rep


def test_valid_checkin(station):
    out = reg.checkin(station, "3NW-4UJ")
    assert out.status == "success"
    e = station.log.entries[-1]
    assert e["type"] == "checkin" and e["seq"] == 2
    assert e["payload"] == {"code": "3NW-4UJ", "source": {"kind": "station"}}
    assert station.state.is_active(("code", "3NW-4UJ"))
    assert out.extra["role"] == "gelb"
    _verify(station)


def test_checkin_input_is_normalised(station):
    assert reg.checkin(station, "  3nw4uj ").status == "success"
    assert station.log.entries[-1]["payload"]["code"] == "3NW-4UJ"


def test_valid_checkout(station):
    reg.checkin(station, "3NW-4UJ")
    out = reg.checkout(station, "3NW-4UJ")
    assert out.status == "success"
    assert station.log.entries[-1]["type"] == "checkout"
    assert not station.state.is_active(("code", "3NW-4UJ"))
    _verify(station)


def test_checkin_again_after_checkout_is_allowed(station):
    reg.checkin(station, "3NW-4UJ")
    reg.checkout(station, "3NW-4UJ")
    assert reg.checkin(station, "3NW-4UJ").status == "success"


def test_valid_walkin_counts_as_checkin(station):
    out = reg.walkin(station, name="Lena Beispiel", role="gelb", skill="Pflegefachkraft", consent=True)
    assert out.status == "success"
    e = station.log.entries[-1]
    assert e["type"] == "walkin"
    p = e["payload"]
    assert p == {"walkin_id": "W-T9-0001", "name": "Lena Beispiel", "role_claimed": "gelb",
                 "skill": "Pflegefachkraft", "consent": True, "consent_version": "1.0",
                 "source": {"kind": "station"}}
    assert station.state.is_active(("walkin_id", "W-T9-0001"))
    # no extra checkin entry was created
    assert [x["type"] for x in station.log.entries] == ["genesis", "walkin"]
    _verify(station)


def test_walkin_ids_unique_and_sequential(station):
    ids = [reg.walkin(station, name=f"P{i}", role="gruen", skill="", consent=True).extra["walkin_id"]
           for i in range(3)]
    assert ids == ["W-T9-0001", "W-T9-0002", "W-T9-0003"]


def test_walkin_checkout_by_id(station):
    reg.walkin(station, name="Tom", role="gruen", skill="", consent=True)
    out = reg.checkout(station, "w-t9-0001")
    assert out.status == "success"
    assert station.log.entries[-1]["payload"] == {"walkin_id": "W-T9-0001", "source": {"kind": "station"}}
    _verify(station)


def test_walkin_can_check_in_again_after_checkout(station):
    reg.walkin(station, name="Tom", role="gruen", skill="", consent=True)
    reg.checkout(station, "W-T9-0001")
    assert reg.checkin(station, "W-T9-0001").status == "success"
    _verify(station)


def test_walkin_requires_name_and_role(station):
    n = len(station.log)
    assert reg.walkin(station, name="  ", role="gelb", skill="", consent=True).status == "invalid"
    assert reg.walkin(station, name="X", role="blau", skill="", consent=True).status == "invalid"
    assert len(station.log) == n


def test_walkin_name_with_umlauts_is_kept(station):
    reg.walkin(station, name="Jörg Müßig", role="rot", skill="Statiker", consent=True)
    assert station.log.entries[-1]["payload"]["name"] == "Jörg Müßig"
    _verify(station)


def test_walkin_start_offset_for_replacement_device(station):
    station.cfg.walkin_start = 501
    assert reg.next_walkin_id(station) == "W-T9-0501"


def test_attendance_consistency(station):
    reg.checkin(station, "3NW-4UJ")
    reg.checkin(station, "84M-6GV")
    reg.walkin(station, name="A", role="gruen", skill="", consent=True)
    reg.checkout(station, "84M-6GV")
    assert set(station.state.active) == {("code", "3NW-4UJ"), ("walkin_id", "W-T9-0001")}
    assert station.state.counts == {"checkin": 2, "checkout": 1, "walkin": 1, "rejected": 0}


def test_every_written_entry_passes_schema(station):
    reg.checkin(station, "3NW-4UJ")
    reg.checkin(station, "3NW-4UJ")
    reg.checkout(station, "9MF-SVJ")
    reg.walkin(station, name="A", role="gruen", skill="", consent=False)
    for e in station.log.entries:
        assert validate_entry_schema(e) == []
