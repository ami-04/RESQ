"""Organiser API client, handover and retry-safe upload (FORMAT.md sections 3, 7, 8).

Network is only touched when the operator explicitly asks (check / upload / status).
Normal registration never contacts the server.

Safety rules implemented here
- The team token comes from the environment only and is never logged or returned.
- Historical entries are never rewritten or re-signed. On a conflict (409) we stop.
- A `handover` is appended right before sending. If the last entry already is a
  handover written less than REUSE_HANDOVER_S ago (e.g. retry after a timeout), it is
  reused instead of writing a second one; otherwise a fresh handover is appended so the
  server's clock measurement stays accurate.
- The server response is authoritative for what was accepted (`accepted_up_to`).
- Uploads from a rehearsal data directory are refused.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable

import requests

from .storage import atomic_write_json, read_json
from .validation import parse_time, verify_log

if TYPE_CHECKING:  # pragma: no cover
    from .station import Station

NDJSON = "application/x-ndjson"
REUSE_HANDOVER_S = 60
MAX_BODY = 5 * 1024 * 1024

STATUS_TEXT = {
    400: "Body unreadable, empty, not UTF-8, or invalid key",
    401: "Team token missing, invalid or revoked",
    403: "Registration deadline passed, or station does not belong to this team",
    409: "Conflict: same seq with different content, or key already taken / station has entries",
    412: "Upload before a key was registered",
    413: "Body larger than 5 MB",
    423: "Uploads are locked (verification phase started)",
    429: "Too many requests, wait briefly",
}


class ApiError(RuntimeError):
    def __init__(self, status: int | None, message: str, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


@dataclass
class ApiResult:
    status: int
    body: dict


class ApiClient:
    def __init__(self, base_url: str, token: str | None, *, timeout: float = 15.0,
                 session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep,
                 retries: int = 3):
        self.base = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self.http = session or requests.Session()
        self.sleep = sleep
        self.retries = retries

    def __repr__(self) -> str:  # never show the token
        return f"ApiClient(base={self.base!r}, token={'set' if self._token else 'missing'})"

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    def _headers(self, auth: bool, content_type: str | None = None, station_id: str | None = None) -> dict:
        h = {"Accept": "application/json"}
        if auth:
            if not self._token:
                raise ApiError(None, "RESQ_TEAM_TOKEN is not set (see README: token configuration)")
            h["Authorization"] = f"Bearer {self._token}"
        if content_type:
            h["Content-Type"] = content_type
        if station_id:
            h["X-Station-Id"] = station_id
        return h

    def _request(self, method: str, path: str, *, auth: bool = True, data: bytes | None = None,
                 json_body: dict | None = None, content_type: str | None = None,
                 params: dict | None = None, station_id: str | None = None,
                 retry: bool = True) -> ApiResult:
        url = self.base + path
        attempts = self.retries if retry else 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = self.http.request(
                    method, url, headers=self._headers(auth, content_type, station_id),
                    data=data, json=json_body, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < attempts:
                    self.sleep(min(2 ** attempt, 8))
                    continue
                raise ApiError(None, f"Server not reachable ({type(exc).__name__}). "
                                     "Offline? Your data is safe locally; retry later.") from exc
            try:
                body = resp.json()
            except ValueError:
                body = {"error": (resp.text or "")[:300]}
            if not isinstance(body, dict):
                body = {"data": body}
            if resp.status_code == 429 and attempt < attempts:
                self.sleep(5)
                continue
            if resp.status_code >= 500 and attempt < attempts:
                self.sleep(min(2 ** attempt, 8))
                continue
            if resp.status_code in (200, 201):
                return ApiResult(resp.status_code, body)
            msg = STATUS_TEXT.get(resp.status_code, f"HTTP {resp.status_code}")
            if body.get("error"):
                msg += f": {body['error']}"
            raise ApiError(resp.status_code, msg, body)
        raise ApiError(None, f"Request failed: {last_exc}")

    # -- endpoints
    def health(self) -> ApiResult:
        return self._request("GET", "/v1/health", auth=False, retry=False)

    def register_key(self, pubkey_b64: str) -> ApiResult:
        return self._request("POST", "/v1/station/key", json_body={"pubkey_b64": pubkey_b64},
                             content_type="application/json", retry=False)

    def check(self, ndjson: bytes) -> ApiResult:
        return self._request("POST", "/v1/check", data=ndjson, content_type=NDJSON)

    def upload(self, ndjson: bytes) -> ApiResult:
        return self._request("POST", "/v1/upload", data=ndjson, content_type=NDJSON)

    def status(self, station_id: str | None = None) -> ApiResult:
        return self._request("GET", "/v1/status", station_id=station_id)

    def findings(self, station_id: str | None = None) -> ApiResult:
        return self._request("GET", "/v1/findings", station_id=station_id)

    def events(self, from_seq: int = 1, limit: int = 500, station_id: str | None = None) -> ApiResult:
        return self._request("GET", "/v1/events", params={"from_seq": from_seq, "limit": limit},
                             station_id=station_id)


# --------------------------------------------------------------------------- handover

def ensure_handover(st: "Station", reuse_window_s: int = REUSE_HANDOVER_S) -> tuple[dict, bool]:
    """Return (handover_entry, created). Appends a fresh handover unless a very recent
    one is already the last entry."""
    with st.write_lock:
        last = st.log.last
        if last and last["type"] == "handover":
            written = parse_time(last["recorded_at"])
            age = (st.now_dt() - written).total_seconds() if written else 1e9
            if 0 <= age <= reuse_window_s:
                return last, False
        seq = st.log.next_seq()
        entry = st.append("handover", {"last_seq": seq, "count": seq})
        return entry, True


# --------------------------------------------------------------------------- sync state

class SyncState:
    def __init__(self, path):
        self.path = path
        self.data = read_json(path, {}) or {}

    @property
    def accepted_up_to(self) -> int:
        return int(self.data.get("accepted_up_to") or 0)

    def save(self, **kw) -> None:
        self.data.update(kw)
        atomic_write_json(self.path, self.data)


def _now_iso(st: "Station") -> str:
    return datetime.now(st.tz).replace(microsecond=0).isoformat()


def local_preflight(st: "Station") -> dict:
    pub = st.meta.get("public_key_b64")
    rep = verify_log(st.log.lines(), expected_pubkey_b64=pub, codes=set(st.codes))
    return rep.as_dict()


def upload(st: "Station", api: ApiClient, *, allow_rehearsal: bool = False) -> dict:
    """Handover + upload. Returns a summary dict. Raises ApiError for blocking problems."""
    is_live = st.cfg.mode == "live" and st.meta.get("mode", "live") == "live"
    if not is_live and not allow_rehearsal:
        raise ApiError(None, "This is a REHEARSAL data directory. Uploading it is blocked to protect "
                             "the competition log. Use the live data directory.")
    if not api.has_token:
        raise ApiError(None, "RESQ_TEAM_TOKEN is not set.")
    sync = SyncState(st.cfg.sync_path)
    handover, created = ensure_handover(st)
    pre = local_preflight(st)
    if not pre["ok"]:
        raise ApiError(None, "Local verification found errors; not uploading. See findings.", pre)
    from_seq = sync.accepted_up_to + 1 if sync.accepted_up_to else 1
    body = st.log.ndjson(from_seq)
    if len(body) > MAX_BODY:
        raise ApiError(413, "Upload body would exceed 5 MB")
    sync.save(last_attempt_at=_now_iso(st), last_attempt_handover_seq=handover["seq"], last_error=None)
    try:
        res = api.upload(body)
    except ApiError as exc:
        sync.save(last_error=str(exc), last_error_status=exc.status)
        raise
    b = res.body
    sync.save(
        accepted_up_to=int(b.get("accepted_up_to") or 0),
        last_upload_at=_now_iso(st),
        last_response=b,
        last_error=None,
        last_error_status=None,
    )
    return {"handover_seq": handover["seq"], "handover_created": created, "sent_from_seq": from_seq,
            "status": res.status, "response": b}


def check_remote(st: "Station", api: ApiClient) -> dict:
    """Dry-run check of the current log (nothing stored on the server, nothing appended locally)."""
    res = api.check(st.log.ndjson())
    SyncState(st.cfg.sync_path).save(last_check_at=_now_iso(st), last_check=res.body)
    return res.body
