"""Local HTTP API used by the browser UI (Flask test client)."""
import pytest

from app import create_app
from backend.sync import ApiClient


@pytest.fixture
def client(station):
    app = create_app(station.cfg, station=station, api=ApiClient("https://example.invalid", None))
    app.testing = True
    return app.test_client()


def test_index_and_phone_pages_render(client):
    r = client.get("/")
    assert r.status_code == 200 and b"RESQ" in r.data
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert client.get("/phone").status_code == 200


def test_no_external_assets(client):
    html = client.get("/").data.decode()
    assert "http://" not in html and "https://" not in html


def test_checkin_flow_over_http(client):
    r = client.post("/api/checkin", json={"id": "3nw-4uj"})
    assert r.status_code == 200 and r.json["status"] == "success" and r.json["seq"] == 2
    r = client.post("/api/checkin", json={"id": "3NW-4UJ"})
    assert r.json["status"] == "rejected" and r.json["reason"] == "already_checked_in"
    r = client.post("/api/checkout", json={"id": "3NW-4UJ"})
    assert r.json["status"] == "success"
    d = client.get("/api/dashboard").json
    assert d["counts"] == {"checkin": 1, "checkout": 1, "walkin": 0, "rejected": 1}
    assert d["active_count"] == 0 and d["pending_upload"] == 4


def test_invalid_input_returns_400_and_writes_nothing(client, station):
    n = len(station.log)
    r = client.post("/api/checkin", json={"id": "??"})
    assert r.status_code == 400 and r.json["status"] == "invalid"
    assert len(station.log) == n


def test_walkin_over_http(client):
    assert client.get("/api/walkin/next-id").json["walkin_id"] == "W-T9-0001"
    r = client.post("/api/walkin", json={"name": "Ana", "role": "gelb", "skill": "Koch", "consent": True})
    assert r.json["walkin_id"] == "W-T9-0001"
    r = client.post("/api/walkin", json={"name": "Nope", "role": "gelb", "consent": False})
    assert r.json["reason"] == "no_consent"
    r = client.post("/api/walkin", json={"name": "Str", "role": "gelb", "consent": "true"})  # not boolean true
    assert r.json["reason"] == "no_consent"


def test_paper_over_http(client, station):
    today = station.now_dt().strftime("%Y-%m-%d")
    body = {"sheet": "P-T9-01", "line": 1, "type": "checkin", "date": today, "time": "00:00",
            "id": "3NW-4UJ", "confirmed": True}
    assert client.post("/api/paper", json=body).json["status"] == "success"
    r = client.post("/api/paper", json=body)
    assert r.status_code == 400 and r.json["duplicate"]


def test_phone_over_http(client):
    ch = client.get("/api/phone/challenge").json["challenge"]
    assert client.post("/api/phone/checkin", json={"code": "3NW-4UJ", "challenge": ch}).json["status"] == "success"
    r = client.post("/api/phone/checkin", json={"code": "84M-6GV", "challenge": "OLD1"})
    assert r.json["reason"] == "remote_suspected"


def test_log_verify_and_readiness(client):
    client.post("/api/checkin", json={"id": "3NW-4UJ"})
    log = client.get("/api/log").json
    assert log["total"] == 2 and log["rows"][0]["type"] == "checkin"
    v = client.get("/api/verify").json
    assert v["ok"] is True
    checks = {c["name"]: c for c in client.get("/api/readiness").json["checks"]}
    assert checks["Code list loaded"]["ok"] and checks["Station key present"]["ok"]
    assert checks["Signed chain valid"]["ok"] and checks["Local storage writable"]["ok"]
    assert checks["Genesis uses this key"]["ok"]
    # never green without a real check
    assert checks["Organiser API reachable"]["ok"] is False
    assert checks["Team token configured"]["ok"] is False


def test_upload_requires_confirmation(client):
    assert client.post("/api/sync/upload", json={}).status_code == 400


def test_upload_without_token_reports_error(client, station):
    r = client.post("/api/sync/upload", json={"confirm": True}).json
    assert r["ok"] is False and "TOKEN" in r["message"]


def test_operator_api_blocked_from_lan(client):
    r = client.post("/api/checkin", json={"id": "3NW-4UJ"}, environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 403
    assert client.get("/phone", environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code == 200


def test_not_initialised_station_refuses(cfg):
    from backend import crypto
    from backend.station import Station
    from backend.storage import KeyStore
    KeyStore(cfg.key_path).save_new(crypto.generate_private_key())
    st = Station.open(cfg)
    try:
        app = create_app(cfg, station=st, api=ApiClient("https://x.invalid", None))
        r = app.test_client().post("/api/checkin", json={"id": "3NW-4UJ"})
        assert r.status_code == 409
    finally:
        st.close()


def test_log_download_jsonl_is_the_exact_signed_log(client, station):
    client.post("/api/checkin", json={"id": "3NW-4UJ"})
    r = client.get("/api/log/download?format=jsonl")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    assert r.data == station.log.ndjson()


def test_log_download_csv_is_readable_and_formula_safe(client):
    client.post("/api/walkin", json={"name": "=HYPERLINK(1)", "role": "gelb", "consent": True})
    r = client.get("/api/log/download?format=csv")
    text = r.data.decode("utf-8-sig")
    assert r.status_code == 200 and text.startswith("seq,recorded_at,type,who")
    import csv, io
    cells = [c for row in csv.reader(io.StringIO(text)) for c in row]
    assert any("HYPERLINK" in c for c in cells)
    assert not any(c[:1] in ("=", "+", "@") for c in cells)


def test_log_download_rejects_unknown_format_and_lan(client, station):
    assert client.get("/api/log/download?format=xml").status_code == 400
    r = client.get("/api/log/download", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 403
