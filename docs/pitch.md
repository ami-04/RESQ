# 3-minute pitch outline

**0:00 Hook (20 s)** — "The network is down, 40 helpers are at the door, and tomorrow someone has to trust this list.
RESQ makes that list trustworthy — offline."

**0:20 Live (80 s)** — Wi-Fi off. Enter a code → green in <1 s. Same code → red `already_checked_in`.
Invented code → `unknown_code`. Walk-in with consent → ID. Refusal → logged without name.
Old phone screenshot → `remote_suspected`. Paper line imported with original time.

**1:40 Trust (40 s)** — Every line is SHA-256 chained and Ed25519 signed; our code reproduces the official
test vectors byte for byte. Show "Verify chain now". Change one letter in a copy → `E_HASH`. Delete a line → `E_LUECKE`.
Handover closes the chain before each upload; retries never rewrite history.

**2:20 Honest limits (30 s)** — Signing proves *integrity, not truth*. A code is a bearer secret: if a friend uses it while
the owner is absent, we can't know. Our phone challenge proves "saw this screen within 90 s", not identity — a live video call beats it.
Stolen laptop = stolen key → replacement station.

**2:50 Close (10 s)** — "When networks fail, trust remains — and we tell you exactly how far."
