# Blackout Station Device Log · Format Specification v0.5

As of 19 Nov 2026 · for participants · all persons and codes are fictitious

This is the English version of `FORMAT.md`. If the two versions ever differ, the German version applies. Field names, values and finding codes (e.g. `E_SIGNATUR`, `level: "warnung"`) are exactly as the server uses them, so some of them are German.

## 1. Overview

Each team runs **one station** with its own `station_id`, e.g. `ST-T1`. The station keeps a log. Every event is one line of JSON (JSON Lines, UTF-8, line ending `\n`). Entries are numbered consecutively, chained by hashes and signed with the station's key.

```
seq 1 genesis ──hash──▶ seq 2 checkin ──hash──▶ seq 3 walkin ──▶ … ──▶ seq n handover
```

Station, paper and the helpers' phones all write into **the same** log. Only the station talks to the server.

## 2. Structure of an entry

```json
{"v":1,"station_id":"ST-T1","seq":2,"type":"checkin",
 "recorded_at":"2026-11-21T09:02:17+01:00",
 "payload":{"code":"K7M-4PX","source":{"kind":"station"}},
 "prev_hash":"…","hash":"…","sig":"…"}
```

| Field | Type | Meaning |
|---|---|---|
| `v` | number | format version, always `1` |
| `station_id` | text | assigned by the organisers: `ST-T1` to `ST-T4` |
| `seq` | number | 1, 2, 3, … without gaps |
| `type` | text | `genesis`, `checkin`, `checkout`, `walkin`, `rejected`, `handover` |
| `recorded_at` | text | time of recording according to the device (section 4) |
| `payload` | object | depends on the type (section 3) |
| `prev_hash` | text | `hash` of the previous entry; for `seq` 1: 64 zeros |
| `hash` | text | SHA-256 of the entry, 64 lowercase hex characters |
| `sig` | text | Ed25519 signature, Base64 |

**Allowed values:** text, integers, `true`/`false`, objects and lists only. No decimal numbers, no `null`.

## 3. Event types

**`genesis`** – always `seq` 1, exactly once
```json
{"station_pubkey":"<Base64, 32 bytes>","team_id":"T1","app_version":"0.3.0"}
```
`station_pubkey` must be the key registered with the organisers.

**`checkin` / `checkout`** – pre-registered persons by code, walk-ins by `walkin_id`
```json
{"code":"K7M-4PX","source":{"kind":"station"}}
{"walkin_id":"W-T1-0003","source":{"kind":"station"}}
```

**`walkin`** – registers a person who turns up spontaneously; also counts as a check-in
```json
{"walkin_id":"W-T1-0003","name":"Lena Beispiel","role_claimed":"gelb",
 "skill":"Nurse","consent":true,"consent_version":"1.0",
 "source":{"kind":"station"}}
```
- The station assigns `walkin_id`: `W-<team>-<4 digits>`, e.g. `W-T1-0003`
- `role_claimed`: `gruen` (green, volunteer), `gelb` (yellow, skilled worker) or `rot` (red, specialist), as stated by the person. The station does not verify qualifications.
- Without `consent: true`, no `walkin` is written.

**`rejected`** – an attempt the station turned down
```json
{"attempt":"checkin","reason":"unknown_code","code":"X3K-9PZ","source":{"kind":"station"}}
```
- `attempt`: what was attempted, `checkin`, `checkout` or `walkin`
- `reason`: why the station refused

| `reason` | Meaning |
|---|---|
| `unknown_code` | code is not on the list |
| `already_checked_in` | person is already checked in at this station |
| `not_checked_in` | check-out without a previous check-in |
| `no_consent` | walk-in without consent |
| `remote_suspected` | phone check-in where the person is probably not on site |
| `other` | other reason, please describe it in `note` (text) |

- Add `code` or `walkin_id` where available, and `source` as for the other types.
- For `no_consent`, do not store a name.
- Rejected attempts belong in the log. Only then can the scoring see that your station fended off an attack.

**Codes** follow the pattern `XXX-XXX`, using `A–Z` without I and O, and `2–9`. You receive the list of valid codes on Friday evening as `codeliste.json` (fields `code`, `role`, `skill`) to build into your app.

### Sources: station, paper, phone

Every `checkin`, `checkout`, `walkin` and `rejected` states its origin in `source.kind`:

| `kind` | Meaning | Additional fields |
|---|---|---|
| `station` | recorded directly on the station device | – |
| `paper` | line from the paper sheet, confirmed by a person | `sheet`, `line`, `confirmed: true`; in the payload also `occurred_at` |
| `phone` | a helper checked in with their own phone, verified by the station | `proof`: object, content is up to you |

```json
"source":{"kind":"paper","sheet":"P-T1-02","line":7,"confirmed":true},
"occurred_at":"2026-11-21T09:08:00+01:00"

"source":{"kind":"phone","proof":{"method":"…","challenge":"…"}}
```

- Unconfirmed paper lines do not go into the log. Photos and signatures are not stored.
- **Phone (bonus task):** The helper's phone sends nothing to the server. It identifies itself at the station, and the station writes the entry. A remote check-in, e.g. with a forwarded screenshot, must not work. How you achieve this and where the limits are belongs in your pitch.

**`handover`** – last entry before every transfer
```json
{"last_seq":42,"count":42}
```
`last_seq` and `count` are both the `seq` of the handover itself (it counts itself). Write the handover immediately before sending. It closes the chain. Without it, the server cannot rule out that entries are missing at the end. The server also uses it to measure your clock offset. After a transfer the station may keep writing; before the next transfer comes a new `handover`.

## 4. Times

All times in ISO 8601 with time zone, e.g. `2026-11-21T09:02:17+01:00`.

| Field | Set by | Precision |
|---|---|---|
| `recorded_at` | the device, automatically when writing or when a paper line is confirmed | to the second |
| `occurred_at` | a person, by hand on the paper sheet | to the minute, seconds always `:00` |

**Wrong clock:** At the `handover`, the server compares its `recorded_at` with the time of receipt. From a deviation of 2 minutes there is `W_UHR`, and all times of that station are corrected by the deviation. Nothing is rejected.

**Plausibility:** After clock correction, all entries of the blackout round must lie within the round. You will learn the exact time on Friday evening.

## 5. Hash and signature

1. Take the entry without `hash` and `sig`.
2. Serialise it **canonically**: keys sorted (including nested ones), no whitespace, UTF-8, non-ASCII characters not escaped.
3. `hash` = SHA-256 of that, as hex.
4. `sig` = Ed25519 signature over the **32 raw bytes** of the hash, as Base64.

```python
import json, hashlib, base64
def canonical(d): return json.dumps(d, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")
body = {k: v for k, v in entry.items() if k not in ("hash", "sig")}
entry["hash"] = hashlib.sha256(canonical(body)).hexdigest()
entry["sig"]  = base64.b64encode(private_key.sign(bytes.fromhex(entry["hash"]))).decode()
```

The line in the file does not need to be canonical. Verification always uses the canonical form.

## 6. Key and station

- Each station generates its Ed25519 key pair **itself**. The private key never leaves the device.
- Register the public key (32 bytes, Base64) by **Friday, 20 Nov, 22:00** via `POST /v1/station/key`. The response contains your `station_id`, which you write into every entry from `genesis` on:
  ```
  curl -X POST https://<server>/v1/station/key \
       -H "Authorization: Bearer <team token>" -H "Content-Type: application/json" \
       -d '{"pubkey_b64":"<your public key>"}'
  → {"station_id":"ST-T1","pubkey_b64":"…","ersetzt":false}
  ```
- As long as your station has not transferred any entries, you may register a new key until 22:00 (e.g. after restarting your app). After that it is fixed.
- After 22:00 or if something goes wrong, the organisers register the key for you: show them your public key.
- **Replacement device:** If the station fails on Saturday, contact the organisers. The replacement device gets a new `station_id` (e.g. `ST-T1B`), a new key and starts a new chain. Whatever the old station already transferred still counts.

## 7. API

The base address and your team token are in your access details. Every request needs:
```
Authorization: Bearer <team token>
```
The token identifies your team. You only see and change your own data. There is no other access to the server.

| Method and path | Purpose |
|---|---|
| `GET /v1/health` | is the server running? No token needed. Also returns `server_time` |
| `POST /v1/station/key` | register the public key, body `{"pubkey_b64":"…"}`, until Friday 22:00. The response contains your `station_id` |
| `POST /v1/check` | **only check** a log, nothing is stored. For testing, as often as you like. Before registration, the key from `genesis` is used (`I_OHNE_SCHLUESSEL`) |
| `POST /v1/upload` | transfer the log, counts for scoring |
| `GET /v1/status` | `accepted_up_to`, number of entries, time of the last transfer |
| `GET /v1/findings` | findings of the latest check |
| `GET /v1/events?from_seq=1&limit=500` | your entries as stored by the server, with corrected time. Page on with `next_from_seq` |

`/v1/check` and `/v1/upload` expect `Content-Type: application/x-ndjson` and the lines of the log. Response:
```json
{"station_id":"ST-T1","stored":true,"accepted_up_to":42,"new":12,"duplicates":30,
 "conflicts":0,"chain_ok":true,"lines":42,"clock_offset_s":-14,"clock_correction_s":0,
 "findings":[{"seq":7,"code":"W_LOGIK","level":"warnung","detail":"…"}]}
```
`clock_offset_s` is the measured deviation of your clock at the `handover` (device minus server), `clock_correction_s` the correction actually applied (0 as long as you are within 2 minutes). Errors are returned as `{"error":"…"}`. `level` is `fehler` (error), `warnung` (warning) or `info`.

Optional header `X-Station-Id`: only needed if, after a replacement device, you want to query an older station. Without it, your active station is used.

- You may always send the whole log or everything from `accepted_up_to + 1`. Known entries with the same hash are skipped silently, so nothing arrives twice.
- If the connection fails, simply retry.
- A known `seq` with **different** content is never overwritten but reported as a conflict.
- Status codes:

| Code | Meaning |
|---|---|
| `200` / `201` | processed (findings are in `findings`) / station created |
| `400` | body unreadable, empty, not UTF-8, or invalid key |
| `401` | token missing, invalid or revoked |
| `403` | registration deadline has passed, or the station is not yours |
| `409` | conflict (same `seq`, different content), key already taken, or station already has entries |
| `412` | upload before a key is registered |
| `413` | body larger than 5 MB |
| `423` | uploads locked (from the start of the check after the blackout round) |
| `429` | too many requests (more than 120 per minute), wait briefly |

## 8. What the server checks

| Code | Level | Meaning |
|---|---|---|
| `E_SCHEMA` | error | required field missing; type, source or `reason` unknown; time unreadable; `occurred_at` with seconds |
| `E_GENESIS` | error | `seq` 1 is not `genesis`, or wrong key |
| `E_HASH` | error | content does not match the hash |
| `E_SIGNATUR` | error | signature does not match the registered key |
| `E_KETTE` | error | `prev_hash` does not match the previous entry (chain) |
| `E_LUECKE` | error | a number is missing (gap) |
| `E_KONFLIKT` | error | same number, different content (conflict) |
| `W_ENDE` | warning | last entry is not a `handover` (end) |
| `W_UHR` | warning | device clock deviates by more than 2 minutes (clock) |
| `W_LOGIK` | warning | contradiction within a valid chain (logic): code not on the code list, check-in while already checked in, check-out without check-in, `walkin_id` assigned twice or never registered, the same code checked in at another station at the same time |
| `I_DUPLIKAT` | info | entry already known, ignored (duplicate) |
| `I_OHNE_SCHLUESSEL` | info | `/v1/check` only: no key registered yet, checked against `genesis` |

**What is accepted:** Only entries that continue the valid chain without gaps. From the first error (`E_*`) on, nothing more is accepted, but everything after it is still checked and reported. Fix the cause and resend from `accepted_up_to + 1`. A line that is not JSON is reported but does not break the chain.

## 9. Testing

The folder `testfaelle/` contains:

- `T1_gueltig.jsonl`: a complete, valid log with 11 entries from all three sources, including one rejected attempt
- `testschluessel.json`: the key T1 is signed with. It is public and only meant for this test. The server refuses it for every real station.
- `T1_erwartet.json`: the 11 expected hashes

**Your app is format-compliant** if, using the test key, it produces the same hashes character for character from the same content. After that, check your own log with `POST /v1/check`.

## 10. How Saturday is measured

There is no script. Who visits your station and when is open, as in a real emergency. Two rules apply to the people with role cards (members of other teams or the organisers):

- **Mandatory visit:** Every role card checks in and later checks out once at every other team's station. Time and order are free.
- **Attacks:** Every station experiences each of the five attacks in the table below exactly once. We do not say when or by whom.

Walk-ins can turn up at any time and in any number.

### The five attacks at the station

Your app should recognise each of them by itself, refuse it and log it as `rejected`:

| Attack | What happens | Expected entry |
|---|---|---|
| Made-up code | Someone gives a code that is on no list | `rejected`, `attempt: checkin`, `reason: unknown_code`, `code` = the code given |
| Double check-in | Someone is checked in at your station and tries again with the same code | `rejected`, `attempt: checkin`, `reason: already_checked_in`, `code` |
| Check-out without check-in | Someone wants to check out with their code without being checked in at your station | `rejected`, `attempt: checkout`, `reason: not_checked_in`, `code` |
| No consent | A walk-in refuses consent | `rejected`, `attempt: walkin`, `reason: no_consent`, **without a name** |
| Remote phone | Someone shows a photo or forwarded copy of another person's phone check-in | `rejected`, `attempt: checkin`, `reason: remote_suspected` |

- The "remote phone" attack only counts if your station offers phone check-in.
- What counts is whether the matching `rejected` entry is in the transferred log; order and time do not matter. For the made-up code, it must be exactly the code given. The number of rejected attempts per station is shown to the jury.
- If an attack slips through as a valid entry (e.g. a check-in with a made-up code), it counts as not detected.

### Check after the round

After the blackout round you transfer your log, then uploads are locked. We manipulate a **copy** of your transferred data: delete entries, change content (with and without a recomputed hash), invent entries, insert duplicates and cut off the end. The verification server must detect every intervention. This only works if your log is correctly chained, signed and closed with a `handover`. Your devices stay with you the whole time.

### Scoring

| Criterion | Share | How it is measured |
|---|---|---|
| Complete and correct | 30 % | share of mandatory visits (check-in and check-out) correctly in the log, and share of entries without errors |
| Manipulation detected: log | 10 % | share of interventions on the copy detected by the verification server |
| Manipulation detected: station | 15 % | share of the five attacks your station refused and logged with the matching `rejected` entry |
| Fast and easy to use | 20 % | jury, check-in time measured with a stopwatch |
| Honest limits | 15 % | jury |
| Pitch | 10 % | jury |

You will learn the exact times of the blackout round, the check and the results on Friday evening.
