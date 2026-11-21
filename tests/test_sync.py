"""Handover and organiser API client. ALL server calls are mocked here."""
import json
from datetime import timedelta

import pytest
import requests

from backend import registration as reg
from backend.sync import ApiClient, ApiError, SyncState, check_remote, ensure_handover, upload
from backend.validation import verify_log

TOKEN = "unit-test-token-not-real"


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    """Records requests; returns queued responses or raises queued exceptions."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, data=None, json=None, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "data": data,
                           "json": json, "params": params})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(responses, token=TOKEN):
    s = FakeSession(responses)
    return ApiClient("https://example.invalid", token, session=s, sleep=lambda _: None), s


def ok_body(n, **kw):
    b = {"station_id": "ST-T9", "stored": True, "accepted_up_to": n, "new": n, "duplicates": 0,
         "conflicts": 0, "chain_ok": True, "lines": n, "clock_offset_s": 0, "clock_correction_s": 0,
         "findings": []}
    b.update(kw)
    return b


# --------------------------------------------------------------------------- handover

def test_handover_counts_itself(station):
    reg.checkin(station, "3NW-4UJ")
    h, created = ensure_handover(station)
    assert created and h["type"] == "handover"
    assert h["payload"] == {"last_seq": 3, "count": 3} and h["seq"] == 3


def test_recent_handover_is_reused_on_retry(station):
    h1, c1 = ensure_handover(station)
    h2, c2 = ensure_handover(station)
    assert c1 and not c2 and h1 == h2


def test_old_handover_gets_fresh_one(station, monkeypatch):
    h1, _ = ensure_handover(station)
    later = station.now_dt() + timedelta(minutes=5)
    monkeypatch.setattr(station, "now_dt", lambda: later)
    monkeypatch.setattr(station, "now", lambda: later.isoformat())
    h2, created = ensure_handover(station)
    assert created and h2["seq"] == h1["seq"] + 1


def test_writing_continues_after_handover_and_new_handover_closes(station):
    ensure_handover(station)
    reg.checkin(station, "3NW-4UJ")
    h, created = ensure_handover(station)
    assert created and h["payload"]["last_seq"] == h["seq"] == 4
    rep = verify_log(station.log.lines(), expected_pubkey_b64=station.keys.public_key_b64())
    assert rep.ok and rep.ends_with_handover


# --------------------------------------------------------------------------- client basics

def test_auth_header_and_ndjson_content_type(station):
    api, s = client([FakeResp(200, ok_body(2))])
    upload(station, api)
    call = s.calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/v1/upload")
    assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert call["headers"]["Content-Type"] == "application/x-ndjson"
    body = call["data"]
    assert isinstance(body, bytes) and body.endswith(b"\n")
    lines = body.decode("utf-8").splitlines()
    assert [json.loads(l)["seq"] for l in lines] == [1, 2]
    assert json.loads(lines[-1])["type"] == "handover"


def test_health_needs_no_token():
    api, s = client([FakeResp(200, {"ok": True, "server_time": "2026-11-21T09:00:00+01:00"})], token=None)
    api.health()
    assert "Authorization" not in s.calls[0]["headers"]


def test_missing_token_is_refused_locally(station):
    api, s = client([], token=None)
    with pytest.raises(ApiError):
        upload(station, api)
    assert not s.calls


def test_token_never_in_repr():
    api, _ = client([])
    assert TOKEN not in repr(api)


def test_request_encoding_is_utf8_unescaped(station):
    reg.walkin(station, name="Jörg Müller", role="gruen", skill="", consent=True)
    api, s = client([FakeResp(200, ok_body(3))])
    upload(station, api)
    assert "Jörg Müller".encode("utf-8") in s.calls[0]["data"]


# --------------------------------------------------------------------------- upload behaviour

def test_successful_upload_stores_accepted_seq(station):
    reg.checkin(station, "3NW-4UJ")
    api, _ = client([FakeResp(200, ok_body(3))])
    res = upload(station, api)
    assert res["response"]["accepted_up_to"] == 3
    assert SyncState(station.cfg.sync_path).accepted_up_to == 3


def test_second_upload_sends_only_new_entries(station):
    api, s = client([FakeResp(200, ok_body(2)), FakeResp(200, ok_body(4, new=2))])
    upload(station, api)
    reg.checkin(station, "3NW-4UJ")
    upload(station, api)
    sent = [json.loads(l)["seq"] for l in s.calls[1]["data"].decode().splitlines()]
    assert sent == [3, 4]


def test_retry_after_network_failure(station):
    api, s = client([requests.ConnectionError("down"), requests.Timeout("slow"), FakeResp(200, ok_body(2))])
    res = upload(station, api)
    assert res["status"] == 200 and len(s.calls) == 3
    assert s.calls[0]["data"] == s.calls[2]["data"]  # identical bytes, nothing re-signed


def test_network_failure_keeps_data_and_reports(station):
    api, _ = client([requests.ConnectionError("x")] * 3)
    with pytest.raises(ApiError) as ei:
        upload(station, api)
    assert ei.value.status is None and "not reachable" in str(ei.value)
    assert station.log.last["type"] == "handover"
    assert SyncState(station.cfg.sync_path).data["last_error"]


def test_retry_later_reuses_handover_no_duplicate(station):
    api, _ = client([requests.ConnectionError("x")] * 3 + [FakeResp(200, ok_body(2))])
    with pytest.raises(ApiError):
        upload(station, api)
    n = len(station.log)
    upload(station, api)
    assert len(station.log) == n


def test_duplicate_acknowledgement(station):
    body = ok_body(2, new=0, duplicates=2,
                   findings=[{"seq": 1, "code": "I_DUPLIKAT", "level": "info", "detail": "known"}])
    api, _ = client([FakeResp(200, body)])
    res = upload(station, api)
    assert res["response"]["duplicates"] == 2


def test_conflict_is_reported_never_rewritten(station):
    before = station.cfg.log_path.read_bytes()
    api, _ = client([FakeResp(409, {"error": "conflict at seq 2"})])
    with pytest.raises(ApiError) as ei:
        upload(station, api)
    assert ei.value.status == 409
    after = station.cfg.log_path.read_bytes()
    assert after.startswith(before)  # only the handover was appended, history unchanged


def test_partial_acceptance_uses_server_value(station):
    reg.checkin(station, "3NW-4UJ")
    body = ok_body(2, chain_ok=False, findings=[{"seq": 3, "code": "E_SIGNATUR", "level": "fehler", "detail": "x"}])
    api, _ = client([FakeResp(200, body)])
    upload(station, api)
    assert SyncState(station.cfg.sync_path).accepted_up_to == 2


@pytest.mark.parametrize("status", [401, 403, 412, 413, 423])
def test_blocking_statuses_raise(station, status):
    api, s = client([FakeResp(status, {"error": "nope"})])
    with pytest.raises(ApiError) as ei:
        upload(station, api)
    assert ei.value.status == status and len(s.calls) == 1


def test_rate_limit_is_retried(station):
    api, s = client([FakeResp(429, {"error": "slow down"}), FakeResp(200, ok_body(2))])
    assert upload(station, api)["status"] == 200 and len(s.calls) == 2


def test_rehearsal_mode_blocks_upload(station):
    station.cfg.mode = "rehearsal"
    api, s = client([FakeResp(200, ok_body(2))])
    with pytest.raises(ApiError):
        upload(station, api)
    assert not s.calls


def test_local_errors_block_upload(station):
    station.log.entries[0]["payload"]["team_id"] = "T0"  # simulate in-memory tamper
    api, s = client([FakeResp(200, ok_body(2))])
    with pytest.raises(ApiError):
        upload(station, api)
    assert not s.calls


def test_check_does_not_append_anything(station):
    n = len(station.log)
    api, s = client([FakeResp(200, ok_body(1, stored=False))])
    check_remote(station, api)
    assert len(station.log) == n
    assert s.calls[0]["url"].endswith("/v1/check")


def test_events_paging_params():
    api, s = client([FakeResp(200, {"events": [], "next_from_seq": None})])
    api.events(from_seq=501, limit=500)
    assert s.calls[0]["params"] == {"from_seq": 501, "limit": 500}
