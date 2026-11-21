# Local API contract (browser UI ↔ Flask), stable for the team

All JSON. Only reachable from the station laptop (loopback); `/phone` + `/static/*` also from the LAN.

Registration responses: `{"status":"success"|"rejected"|"invalid"|"error","message",...}` with
`seq,type,recorded_at` when something was written and `reason` for rejections.
HTTP 200 = written (success or rejected) · 400 = invalid input, **nothing written** · 409 = not initialised · 500 = storage error.

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/checkin` | `{"id": "ABC-DEF" \| "W-T1-0001"}` | |
| POST | `/api/checkout` | `{"id": ...}` | |
| GET | `/api/walkin/next-id` | – | preview only |
| POST | `/api/walkin` | `{"name","role","skill","consent": true}` | `consent` must be boolean `true`; anything else → `no_consent` rejected, name discarded |
| POST | `/api/paper` | `{"sheet","line","type":"checkin\|checkout\|walkin","date":"YYYY-MM-DD","time":"HH:MM","id"\|name/role/skill/consent,"confirmed":true}` | duplicate sheet+line → 400 `duplicate:true` |
| GET | `/api/phone/challenge` | – | `{"challenge","rotates_in_s"}` |
| POST | `/api/phone/checkin` | `{"code","challenge"}` | |
| GET | `/api/dashboard` | – | counts, active list, pending upload, timezone |
| GET | `/api/log?limit=` | – | newest first |
| GET | `/api/verify` | – | local verification report (server finding codes) |
| GET | `/api/readiness[?probe=1]` | – | `probe=1` also calls `/v1/health` |
| GET | `/api/sync` | – | stored sync state |
| POST | `/api/sync/health` · `/check` · `/status` | `{}` | organiser API calls |
| POST | `/api/sync/upload` | `{"confirm": true}` | handover + upload |

Organiser API (FORMAT.md §7) is wrapped by `backend/sync.py::ApiClient`:
`health, register_key, check, upload, status, findings, events` — Bearer token, `application/x-ndjson`.
