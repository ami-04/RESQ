"""Every mandatory workflow must work with ALL network access blocked."""
import socket

import pytest

from backend import paper
from backend import registration as reg
from backend.sync import ApiClient, ApiError, upload
from backend.validation import verify_log


@pytest.fixture
def no_network(monkeypatch):
    def blocked(*a, **k):
        raise OSError("network disabled for this test")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def test_all_registration_workflows_offline(station, no_network):
    assert reg.checkin(station, "3NW-4UJ").status == "success"
    assert reg.checkin(station, "3NW-4UJ").reason == "already_checked_in"
    assert reg.checkin(station, "X3K-9PZ").reason == "unknown_code"
    assert reg.checkout(station, "9MF-SVJ").reason == "not_checked_in"
    assert reg.walkin(station, name="A", role="gruen", skill="", consent=True).status == "success"
    assert reg.walkin(station, name="B", role="gruen", skill="", consent=False).reason == "no_consent"
    out = paper.import_line(station, sheet="P-T9-01", line=1, event_type="checkin", confirmed=True,
                            date=station.now_dt().strftime("%Y-%m-%d"), time="00:00", identifier="84M-6GV")
    assert out.status == "success"
    assert reg.checkout(station, "3NW-4UJ").status == "success"
    rep = verify_log(station.log.lines(), expected_pubkey_b64=station.keys.public_key_b64(), codes=set(station.codes))
    assert rep.ok


def test_upload_offline_fails_gracefully_and_keeps_data(station, no_network):
    reg.checkin(station, "3NW-4UJ")
    api = ApiClient("https://hackathon.invalid", "dummy", sleep=lambda _: None, timeout=1)
    with pytest.raises(ApiError):
        upload(station, api)
    assert reg.checkout(station, "3NW-4UJ").status == "success"  # station keeps working


def test_ui_is_served_offline(station, no_network):
    from app import create_app
    app = create_app(station.cfg, station=station, api=ApiClient("https://x.invalid", None))
    c = app.test_client()
    for path in ("/", "/phone", "/static/app.js", "/static/style.css", "/static/phone.js"):
        assert c.get(path).status_code == 200, path
