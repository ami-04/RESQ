"""Phone check-in with live station challenge (remote_suspected detection)."""
from backend.phone import ChallengeBoard, phone_checkin
from backend.validation import verify_log


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def board(clock):
    return ChallengeBoard(ttl_s=90, rotate_s=30, clock=clock, wall=lambda: 1_790_000_000.0)


def test_live_challenge_accepted(station):
    c = Clock(); b = board(c)
    ch = b.current()["challenge"]
    c.t += 10
    out = phone_checkin(station, b, "3NW-4UJ", ch.lower())
    assert out.status == "success"
    src = station.log.entries[-1]["payload"]["source"]
    assert src["kind"] == "phone" and src["proof"]["challenge"] == ch and src["proof"]["age_s"] == 10
    assert verify_log(station.log.lines(), expected_pubkey_b64=station.keys.public_key_b64()).ok


def test_old_screenshot_is_remote_suspected(station):
    c = Clock(); b = board(c)
    ch = b.current()["challenge"]
    c.t += 200  # photo forwarded minutes later
    b.current()
    out = phone_checkin(station, b, "3NW-4UJ", ch)
    assert out.status == "rejected" and out.reason == "remote_suspected"
    p = station.log.entries[-1]["payload"]
    assert p["attempt"] == "checkin" and p["code"] == "3NW-4UJ" and p["source"]["kind"] == "phone"
    assert not station.state.active


def test_made_up_challenge_is_remote_suspected(station):
    c = Clock(); b = board(c)
    b.current()
    assert phone_checkin(station, b, "3NW-4UJ", "ZZZZ").reason == "remote_suspected"


def test_replay_of_same_pass_is_remote_suspected(station):
    c = Clock(); b = board(c)
    ch = b.current()["challenge"]
    assert phone_checkin(station, b, "3NW-4UJ", ch).status == "success"
    assert phone_checkin(station, b, "3NW-4UJ", ch).reason == "remote_suspected"


def test_live_pass_still_applies_station_rules(station):
    c = Clock(); b = board(c)
    ch = b.current()["challenge"]
    assert phone_checkin(station, b, "X3K-9PZ", ch).reason == "unknown_code"


def test_challenge_rotates(station):
    c = Clock(); b = board(c)
    a = b.current()["challenge"]
    c.t += 31
    assert b.current()["challenge"] != a
