# Team workflow

| Dev | Owns | Files |
|---|---|---|
| 1 Backend | crypto, log, storage, organiser API | `backend/crypto.py validation.py storage.py station.py sync.py manage.py` |
| 2 Frontend | forms, dashboard, paper UI | `templates/ static/ backend/routes.py` (contract: `docs/api-contract.md`) |
| 3 QA/Product | tests, matrix, docs, demo | `tests/ docs/ README.md` |

Business rules (`registration.py paper.py phone.py`) change only with a test in the same PR.

**Branches:** `main` = always demo-able. Work on `feature/<area>-<topic>`, PR into the team feature branch, then `main`.
**Before every push:** `python -m pytest` must be green; the official-vector test must never be skipped.
**Merge order when integrating:** crypto/storage → registration/paper/phone → sync → routes → UI → docs.
**Never commit:** `.env`, `data/live/`, `data/rehearsal/`, any `station_key.json`, screenshots with the token.
If a secret was committed: rotate it with the organisers; removing it from history is not enough.
