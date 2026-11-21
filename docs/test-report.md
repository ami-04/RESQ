# Test report

Run on 20.11.2026 in the build sandbox (Linux, Python 3.13, Flask 3.1, cryptography 50).
**Re-run on the station laptop (Windows) before the round:** `python -m pytest`.

## Automated results
`python -m pytest` → **128 passed, 0 failed, 1 skipped** (the skip is the opt-in browser test).
`RESQ_UI_TESTS=1 python -m pytest tests/test_ui.py` → **1 passed** (headless Chrome).

| File | Tests | Covers |
|---|---|---|
| test_crypto.py | 11 | canonical JSON, UTF-8, SHA-256, raw-digest Ed25519, **official T1 vectors** |
| test_registration.py | 13 | check-in/out, walk-in, IDs, attendance consistency |
| test_rejections.py | 18 | all 4 non-phone attacks, malformed input, unknown walk-in IDs |
| test_phone.py | 6 | live challenge, stale screenshot, made-up challenge, replay |
| test_paper.py | 12 | confirmation, duplicates (also after restart), occurred/recorded time |
| test_storage.py | 13 | restart, torn write recovery, corruption, concurrency, key protection |
| test_tamper.py | 12 | 6 manipulation types on a log copy + wrong key, non-JSON line, null |
| test_sync.py | 27 | handover, auth header, NDJSON, retry, 409/401/403/412/413/423/429, partial acceptance, rehearsal block |
| test_api.py | 12 | HTTP endpoints, CSP/no CDN, LAN restriction, readiness honesty |
| test_offline.py | 3 | all workflows with sockets blocked |
| test_integration.py | 1 | full station day incl. restart and (mocked) upload |

## Official vectors
`T1_gueltig.jsonl` with `testschluessel.json`: **11/11 hashes and 11/11 signatures identical** to `T1_erwartet.json`.
Local verifier on T1: `ok`, `accepted_up_to = 11`, ends with handover. (With our real code list it also
reports `W_LOGIK` for T1's fictional codes; that is expected.)

## Manual / browser checks performed (headless Chrome against the real app)
Check-in → duplicate → unknown code → check-out w/o check-in → check-out; walk-in with and without consent;
phone live + stale challenge; paper unconfirmed / confirmed / duplicate; log verify; rehearsal upload blocked.
Measured check-in round trip (type → Enter → feedback): **≈ 50–100 ms**. No JavaScript errors.

## Not verified — must be done by the team
| Item | Why not | How |
|---|---|---|
| Real `/v1/check` with the registered key | organiser host not reachable from the build sandbox | `python manage.py --data-dir data/rehearsal --mode rehearsal check` |
| Station public key registration | done by the team earlier (not observed by us) | `key-import --expect-pub <registered key>` proves the match |
| Real `/v1/upload` | must only happen with the live log | Saturday, Sync tab |
| Windows file lock (`msvcrt`) and fsync path | sandbox is Linux | `python -m pytest` on the laptop (`test_second_process_cannot_open_same_data_dir`) |
| `infos.zip` requirements | file not provided | re-audit matrix when available |

## Readiness checklist by scoring category
- **Complete & correct (30 %)**: [ ] key imported & matches registration · [ ] live genesis at round start · [ ] clock synced (Sync → Test connection, |offset| < 120 s) · [ ] final handover + upload · [ ] `/v1/findings` free of `E_*`
- **Manipulation – log (10 %)**: [x] chain + signatures + handover · [ ] one final upload at the end (see threat model)
- **Manipulation – station (15 %)**: [x] 5/5 attacks auto-rejected & logged (phone offered)
- **Speed (20 %)**: [x] Enter/Shift+Enter, auto-dash, autofocus · [ ] operators practise 10 check-ins each
- **Honest limits (15 %)**: [x] `docs/threat-model.md`
- **Pitch (10 %)**: [x] `docs/pitch.md` · [ ] rehearse with stopwatch
