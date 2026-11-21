# Operator guide (print this)

**Start:** `python app.py` → open http://127.0.0.1:5000 . Header shows "● recording locally".
Works without internet. Everything you do is signed and saved immediately.

## Check-in / check-out (F1)
1. Type the code (dash optional, lower case fine) → **Enter** = check in.
2. **Shift+Enter** (or blue button) = check out. Walk-ins check out with their ID `W-T1-0001`.
3. Green = done. Red = **rejected and logged** — this is correct behaviour for:
   unknown code · already checked in · check-out without check-in.
   Yellow = typo, nothing saved → fix and retry.

## Walk-in (F2)
Name → role as the person states it (gruen/gelb/rot) → skill (optional) → read the consent sentence aloud.
- Agrees → tick → **Register & check in**. Tell them their ID.
- Refuses → **Person declines consent**. Nothing about them is stored (logged as `no_consent`).

## Phone check-in (F3, bonus)
Turn the screen to the helper; they type their code + the 4-letter challenge on their phone (`/phone`).
Type code + challenge from their pass. Old/forwarded screenshots are rejected automatically (`remote_suspected`).

## Paper backup (when the laptop is down)
Paper sheet columns: **Sheet ID (P-T1-01) · line no. · time (HH:MM) · in/out/walk-in · code or W-ID · name/role/skill (walk-in) · consent ☐**.
No signatures, no photos.
Back on the laptop → **Import paper (F4)**: sheet, line, date, time **from the paper**, type, code →
tick "I have checked this line" → Import. Line number advances automatically.
Importing the same sheet+line twice is refused.

## Handover & upload (team lead)
Sync tab: Test connection → Check log on server → Write handover & upload → Confirm.
Errors never damage the local log; just retry.

## Live demo (3 min, use the rehearsal data dir!)
1. Start in rehearsal mode, show Readiness (all real checks).
2. Turn Wi-Fi off. Check in `3NW-4UJ` (Enter). 3. Same code again → red `already_checked_in`.
4. Made-up `X3K-9PZ` → `unknown_code`. 5. Walk-in Lena (gelb) → `W-T1-000x`; second walk-in declines → `no_consent`.
6. Phone: live challenge accepted; typed old challenge → `remote_suspected`.
7. Import paper line P-T1-01 #3. 8. Activity log → **Verify chain now** (green).
9. Wi-Fi on → Test connection (clock offset) → Check log on server.
Upload in rehearsal mode is blocked — say why: "we never risk the production log in a demo".
