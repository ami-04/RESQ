"""Local JSON API used by the browser UI (contract: docs/api-contract.md)."""
from __future__ import annotations

import hashlib
import os
import uuid
from collections import Counter
from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, request

from . import finder as finder_mod
from . import paper as paper_mod
from . import phone as phone_mod
from . import registration as reg
from .storage import StorageError
from .sync import ApiError, SyncState, check_remote, local_preflight, upload
from .validation import verify_log

bp = Blueprint("resq", __name__)


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@bp.before_app_request
def _operator_only():
    """If the station is served on the local network (for the /phone page), only the
    station laptop itself may use the operator API and screens. Phones get /phone only."""
    if request.remote_addr in LOOPBACK:
        return None
    if request.path in ("/phone", "/favicon.ico") or request.path.startswith("/static/"):
        return None
    return jsonify({"status": "error", "message": "Operator access only from the station device."}), 403


def _st():
    return current_app.config["STATION"]


def _api():
    return current_app.config["API"]


def _board():
    return current_app.config["BOARD"]


def _json():
    return request.get_json(silent=True) or {}


def _guard(fn):
    try:
        return fn()
    except StorageError as exc:
        return jsonify({"status": "error", "message": f"Storage problem: {exc}"}), 500
    except Exception as exc:  # never crash the operator screen
        current_app.logger.exception("operation failed")
        return jsonify({"status": "error", "message": f"Unexpected error: {type(exc).__name__}"}), 500


def _outcome(out):
    code = 200 if out.status in ("success", "rejected") else 400
    return jsonify(out.as_dict()), code


def _not_ready():
    st = _st()
    if not st.initialised:
        return jsonify({"status": "error", "message": "Station not initialised. See README: setup."}), 409
    return None


# --------------------------------------------------------------------------- pages

@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/favicon.ico")
def favicon():
    return "", 204


@bp.get("/phone")
def phone_page():
    return render_template("phone.html")


# --------------------------------------------------------------------------- registration

@bp.post("/api/checkin")
def api_checkin():
    return _not_ready() or _guard(lambda: _outcome(reg.checkin(_st(), _json().get("id"))))


@bp.post("/api/checkout")
def api_checkout():
    return _not_ready() or _guard(lambda: _outcome(reg.checkout(_st(), _json().get("id"))))


@bp.post("/api/walkin")
def api_walkin():
    d = _json()
    return _not_ready() or _guard(lambda: _outcome(reg.walkin(
        _st(), name=d.get("name"), role=d.get("role"), skill=d.get("skill", ""),
        consent=d.get("consent") is True)))


@bp.get("/api/walkin/next-id")
def api_next_walkin():
    st = _st()
    if not st.initialised:
        return jsonify({"walkin_id": None})
    return jsonify({"walkin_id": reg.next_walkin_id(st)})


@bp.post("/api/paper")
def api_paper():
    d = _json()
    return _not_ready() or _guard(lambda: _outcome(paper_mod.import_line(
        _st(), sheet=d.get("sheet"), line=d.get("line"), event_type=d.get("type"),
        confirmed=d.get("confirmed") is True, date=d.get("date"), time=d.get("time"),
        identifier=d.get("id"), name=d.get("name"), role=d.get("role"), skill=d.get("skill", ""),
        consent=d.get("consent") is True)))


@bp.get("/api/phone/challenge")
def api_phone_challenge():
    return jsonify(_board().current())


@bp.post("/api/phone/checkin")
def api_phone_checkin():
    d = _json()
    return _not_ready() or _guard(lambda: _outcome(
        phone_mod.phone_checkin(_st(), _board(), d.get("code"), d.get("challenge"))))


# --------------------------------------------------------------------------- read models

def _person_label(st, key):
    kind, value = key
    if kind == "code":
        info = st.codes.get(value, {})
        return {"id": value, "kind": "code", "role": info.get("role", ""), "skill": info.get("skill", ""), "name": ""}
    w = st.state.walkins.get(value, {})
    return {"id": value, "kind": "walkin", "role": w.get("role", ""), "skill": w.get("skill", ""),
            "name": w.get("name", "")}


@bp.get("/api/finder")
def api_finder():
    """Read-only skill search over the people on site now (never writes to the log)."""
    q = (request.args.get("q") or "")[:80]
    role = request.args.get("role") or ""
    return jsonify(finder_mod.search(_st(), q, role))


@bp.get("/api/dashboard")
def api_dashboard():
    st = _st()
    s = st.state
    active = []
    for key, info in s.active.items():
        p = _person_label(st, key)
        p["since"] = info["since"]
        active.append(p)
    active.sort(key=lambda p: p["since"], reverse=True)
    sync = SyncState(st.cfg.sync_path)
    total = len(st.log)
    return jsonify({
        "station_id": st.station_id,
        "team_id": st.team_id,
        "mode": st.cfg.mode,
        "initialised": st.initialised,
        "entries": total,
        "active_count": len(active),
        "active": active,
        "by_role": dict(Counter(p["role"] for p in active)),
        "counts": s.counts,
        "rejected_by_reason": s.rejected_by_reason,
        "accepted_up_to": sync.accepted_up_to,
        "pending_upload": max(0, total - sync.accepted_up_to),
        "last_handover_seq": s.last_handover_seq,
        "now": st.now(),
        "timezone": st.cfg.timezone,
    })


def _describe(e):
    p = e["payload"]
    src = p.get("source", {}) if isinstance(p, dict) else {}
    who = p.get("code") or p.get("walkin_id") or ""
    if e["type"] == "walkin":
        who = f"{p['walkin_id']} · {p['name']}"
    detail = ""
    if e["type"] == "rejected":
        detail = f"{p['attempt']} → {p['reason']}" + (f" ({p['note']})" if p.get("note") else "")
    elif e["type"] == "handover":
        detail = f"last_seq {p['last_seq']}"
    elif e["type"] == "genesis":
        detail = f"team {p['team_id']} · app {p['app_version']}"
    source = src.get("kind", "")
    if source == "paper":
        source = f"paper {src.get('sheet')}#{src.get('line')} @ {p.get('occurred_at', '')[11:16]}"
    return {"seq": e["seq"], "type": e["type"], "recorded_at": e["recorded_at"], "who": who,
            "detail": detail, "source": source, "hash": e["hash"][:12]}


@bp.get("/api/log")
def api_log():
    st = _st()
    limit = min(int(request.args.get("limit", 200)), 2000)
    entries = st.log.entries[-limit:]
    sync = SyncState(st.cfg.sync_path)
    rows = [_describe(e) | {"uploaded": e["seq"] <= sync.accepted_up_to} for e in reversed(entries)]
    return jsonify({"total": len(st.log), "rows": rows})


def _csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection (names are typed by people)."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@bp.get("/api/log/download")
def api_log_download():
    """Download the whole log. jsonl = the exact signed log (for backup / verification),
    csv = a readable table for Excel/Numbers (not signed, for reading only)."""
    import csv
    import io
    from flask import Response

    st = _st()
    fmt = request.args.get("format", "jsonl")
    stamp = st.now_dt().strftime("%Y%m%d-%H%M")
    name = f"{st.station_id or 'station'}_{stamp}"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["seq", "recorded_at", "type", "who", "detail", "source", "hash"])
        for e in st.log.entries:
            d = _describe(e)
            w.writerow([d["seq"], d["recorded_at"], d["type"], _csv_safe(d["who"]), _csv_safe(d["detail"]),
                        _csv_safe(d["source"]), e["hash"]])
        data = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel shows umlauts correctly
        mime, ext = "text/csv; charset=utf-8", "csv"
    elif fmt == "jsonl":
        data, mime, ext = st.log.ndjson(), "application/x-ndjson", "jsonl"
    else:
        return jsonify({"status": "invalid", "message": "format must be jsonl or csv"}), 400
    return Response(data, mimetype=mime,
                    headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})


@bp.get("/api/verify")
def api_verify():
    return jsonify(local_preflight(_st()))


# --------------------------------------------------------------------------- readiness

def readiness(st, api, probe_api: bool = False) -> list[dict]:
    checks = []

    def add(name, ok, detail, level=None):
        checks.append({"name": name, "ok": bool(ok), "level": level or ("ok" if ok else "fail"), "detail": detail})

    if st.codelist_error:
        add("Code list loaded", False, st.codelist_error)
    else:
        digest = hashlib.sha256(st.cfg.codelist_path.read_bytes()).hexdigest()[:12]
        add("Code list loaded", len(st.codes) > 0, f"{len(st.codes)} codes · sha256 {digest}")

    try:
        pub = st.keys.public_key_b64() if st.keys.exists() else None
        add("Station key present", pub is not None, f"public key {pub}" if pub else "no key file")
    except Exception as exc:
        pub = None
        add("Station key present", False, str(exc))

    if st.initialised:
        g = st.log.entries[0]["payload"]["station_pubkey"]
        add("Genesis uses this key", pub == g, "matches" if pub == g else "MISMATCH: genesis key differs from key file")
    else:
        add("Genesis written", False, "station not initialised yet")

    try:
        probe = st.cfg.data_dir / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        with open(probe, "rb") as fh:
            os.fsync(fh.fileno())
        probe.unlink()
        add("Local storage writable", True, str(st.cfg.data_dir))
    except OSError as exc:
        add("Local storage writable", False, str(exc))

    if st.log.corruption:
        add("Signed chain valid", False, st.log.corruption)
    elif st.initialised:
        rep = verify_log(st.log.lines(), expected_pubkey_b64=st.meta.get("public_key_b64"))
        errs = [f["code"] for f in rep.findings if f.level == "fehler"]
        add("Signed chain valid", not errs, f"{rep.entries} entries, hash+signature+chain verified"
            if not errs else "errors: " + ", ".join(sorted(set(errs))))
    else:
        add("Signed chain valid", False, "no log yet")

    add("Mode", st.cfg.mode == "live", "LIVE log" if st.cfg.mode == "live" else "REHEARSAL (uploads blocked)",
        level="ok" if st.cfg.mode == "live" else "warn")
    add("Team token configured", api.has_token, "set via environment" if api.has_token else "RESQ_TEAM_TOKEN missing",
        level="ok" if api.has_token else "warn")

    if probe_api:
        try:
            res = api.health()
            add("Organiser API reachable", True, f"server_time {res.body.get('server_time', '?')}")
        except ApiError as exc:
            add("Organiser API reachable", False, str(exc), level="warn")
    else:
        add("Organiser API reachable", False, "not checked (offline mode; press 'Test connection')", level="unknown")
    return checks


@bp.get("/api/readiness")
def api_readiness():
    probe = request.args.get("probe") == "1"
    return jsonify({"checks": readiness(_st(), _api(), probe_api=probe)})


# --------------------------------------------------------------------------- sync

@bp.get("/api/sync")
def api_sync():
    st = _st()
    sync = SyncState(st.cfg.sync_path)
    d = dict(sync.data)
    d["entries"] = len(st.log)
    d["pending_upload"] = max(0, len(st.log) - sync.accepted_up_to)
    d["last_is_handover"] = bool(st.log.last and st.log.last["type"] == "handover")
    d["mode"] = st.cfg.mode
    d["token"] = bool(_api().has_token)
    return jsonify(d)


@bp.post("/api/sync/health")
def api_sync_health():
    st = _st()
    try:
        res = _api().health()
    except ApiError as exc:
        return jsonify({"online": False, "message": str(exc)}), 200
    body = res.body
    offset = None
    if isinstance(body.get("server_time"), str):
        try:
            srv = datetime.fromisoformat(body["server_time"].replace("Z", "+00:00"))
            if srv.tzinfo is not None:
                offset = int((st.now_dt() - srv).total_seconds())
        except ValueError:
            pass
    return jsonify({"online": True, "server_time": body.get("server_time"), "clock_offset_s": offset})


@bp.post("/api/sync/check")
def api_sync_check():
    try:
        return jsonify({"ok": True, "result": check_remote(_st(), _api())})
    except ApiError as exc:
        return jsonify({"ok": False, "message": str(exc), "status": exc.status, "body": exc.body}), 200


@bp.post("/api/sync/upload")
def api_sync_upload():
    if not _json().get("confirm"):
        return jsonify({"ok": False, "message": "Upload needs explicit confirmation."}), 400
    try:
        return jsonify({"ok": True, "result": upload(_st(), _api())})
    except ApiError as exc:
        return jsonify({"ok": False, "message": str(exc), "status": exc.status, "body": exc.body}), 200


@bp.post("/api/sync/status")
def api_sync_status():
    try:
        status = _api().status()
        fi = _api().findings()
        if isinstance(status.body.get("accepted_up_to"), int):
            # the server is authoritative for what has been accepted
            SyncState(_st().cfg.sync_path).save(accepted_up_to=status.body["accepted_up_to"])
        return jsonify({"ok": True, "status": status.body, "findings": fi.body})
    except ApiError as exc:
        return jsonify({"ok": False, "message": str(exc), "status": exc.status}), 200
