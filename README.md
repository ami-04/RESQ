# RESQ — Blackout Station

> **When networks fail, trust remains.**

Offline-first registration station for the Ortsbereit hackathon. Every check-in, check-out, walk-in,
paper line and rejected attack is written to an append-only, hash-chained, Ed25519-signed JSONL log
(`FORMAT.md` v0.5). Normal registration never needs the network; the log is handed over and uploaded
when the connection is back.

- Reproduces the official T1 test vectors character for character (11/11 hashes and signatures).
- Detects all five station attacks automatically and logs them as `rejected`.
- 128 automated tests + 1 opt-in browser test. See `docs/test-report.md`.

## 1. Install (Windows PowerShell / macOS / Linux)

```powershell
# Windows
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest            # must say: 128 passed, 1 skipped
```
```bash
# macOS / Linux
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
```

## 2. Configure the team token (secret)

```bash
cp .env.example .env        # Windows: copy .env.example .env
```
Edit `.env` and set `RESQ_TEAM_TOKEN=...`. `.env` is in `.gitignore`. **Never** put the token in code,
commits, screenshots or chat. The app reads it only from the environment and never prints it.

## 3. Your already registered key (IMPORTANT)

You registered a public key with the organisers. The station **must** sign with the matching private key,
otherwise every entry fails with `E_GENESIS` / `E_SIGNATUR`.

Import the private key you generated (pick the format you have) and let the tool check it against the
public key you registered:

```bash
python manage.py key-import --seed-hex <64 hex chars> --expect-pub <your registered public key>
# or: --seed-b64 <base64>   --pem path\to\key.pem   --json path\to\key.json
python manage.py key-show
```
The key is stored in `data/live/station_key.json` (git-ignored). The tool refuses to overwrite an
existing key and refuses the public T1 test key.

> Lost the private key? Then the registered key is useless. Before **22:00 Friday** you may register a new
> one (`python manage.py key-generate --new-station` then `python manage.py register-key --confirm-replace`),
> after that ask the organisers. Never generate a new key "just to try".

## 4. Rehearse tonight (does not touch the live log)

```bash
python manage.py --data-dir data/rehearsal --mode rehearsal key-import --seed-hex <same key> --expect-pub <pub>
python manage.py --data-dir data/rehearsal --mode rehearsal init --station-id <your ST-Tx>
$env:RESQ_DATA_DIR="data/rehearsal"; $env:RESQ_MODE="rehearsal"; python app.py   # Windows PowerShell
# RESQ_DATA_DIR=data/rehearsal RESQ_MODE=rehearsal python app.py               # macOS/Linux
```
Do a few check-ins in the browser, then validate against the real server **without storing anything**:
```bash
python manage.py --data-dir data/rehearsal --mode rehearsal check
```
Expected: `chain_ok: true`, no `E_*` findings (a `W_ENDE` is normal because a check does not write a handover).
Uploading from a rehearsal directory is blocked by design.

## 5. Set up the live station (Saturday, right before the round)

Spec §4: all entries of the blackout round must lie inside the round time. To be safe, write the live
genesis at the start of the round:
```bash
python manage.py init --station-id <ST-Tx from the registration response>
python app.py
```
Open http://127.0.0.1:5000 → **Readiness** tab: everything green except "API reachable" (grey until tested).

## 6. Operate
See `docs/operator-guide.md` (one page, for whoever sits at the laptop).
Quick keys: **Enter** = check in · **Shift+Enter** = check out · **F2** walk-in · **F3** phone · **F4** paper.

## 7. Handover & upload
Sync tab → *Test connection* (shows clock offset) → *Check log on server* (dry run) →
*Write handover & upload* → confirm. Or: `python manage.py upload --yes` (stop the web app first; only one writer).
The upload writes the `handover` immediately before sending, retries network failures safely, never rewrites history,
and stores what the server reports as `accepted_up_to`.

## 8. Validate a log
```bash
python manage.py verify                       # live log, against its genesis key
python manage.py verify --file some.jsonl --pubkey <b64>
```

## 9. Phone check-in (bonus) on the station Wi-Fi
Set `RESQ_HOST=0.0.0.0`. Phones open `http://<laptop-ip>:5000/phone`; the operator API stays restricted to the laptop itself.

## Project layout
```
app.py  manage.py  config.py
backend/  crypto · validation · storage · station · registration · paper · phone · sync · routes
templates/ static/   (no CDN)
tests/   docs/   testfaelle/   data/codeliste.json
```
Docs: `docs/requirements-matrix.md`, `api-contract.md`, `threat-model.md`, `operator-guide.md`,
`test-report.md`, `pitch.md`, `../CONTRIBUTING.md`.

## Troubleshooting
| Symptom | Fix |
|---|---|
| "Another RESQ process is already using …" | a second `app.py`/CLI is running; close it |
| Readiness: "Genesis uses this key: MISMATCH" | wrong key imported. **Stop.** Don't register anything; check `key-show` vs. registered key |
| `E_GENESIS`/`E_SIGNATUR` on `/v1/check` | log was signed with a key that is not the registered one |
| `W_UHR` | fix the laptop clock (Windows: Settings → Time → Sync now) before the next handover |
| `423` on upload | uploads are locked; nothing more can be sent |
| `401` | token missing/wrong in `.env` |
| Log damaged message | do not edit `log.jsonl`; restore from backup, ask the team lead |
