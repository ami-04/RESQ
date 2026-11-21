"""Attack type B rehearsal: manipulate COPIES of the station log and check that every
manipulation is detected.

The real log is only read, never written. Each manipulated copy is saved to the output
folder so you can open it and see exactly what was changed.

    python tools/attack_b.py --data-dir data/rehearsal --mode rehearsal
    python tools/attack_b.py --data-dir data/rehearsal --mode rehearsal --server   # also ask /v1/check

Local check  = the same verification rules as the organisers' server (backend/validation.py).
--server     = sends each copy to POST /v1/check (dry run: the server stores NOTHING).
               Needs RESQ_TEAM_TOKEN in .env and only makes sense for a log signed with your
               REGISTERED key; a practice-key log fails every copy with E_GENESIS.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import crypto  # noqa: E402
from backend.station import load_codelist  # noqa: E402
from backend.storage import KeyStore  # noqa: E402
from backend.sync import ApiClient, ApiError  # noqa: E402
from backend.validation import verify_log  # noqa: E402
from config import load_config  # noqa: E402


# ---------------------------------------------------------------- helpers

def dump(entries: list[dict]) -> bytes:
    return b"".join(crypto.canonical(e) + b"\n" for e in entries)


def fake_sig() -> str:
    """An attacker has no private key: the best they can do is a random signature."""
    return base64.b64encode(os.urandom(64)).decode()


def rehash(e: dict) -> dict:
    e["hash"] = crypto.compute_hash(e)
    return e


def rechain(entries: list[dict], start: int) -> None:
    """Recompute prev_hash/hash from index `start` on, as a careful attacker would.
    Signatures cannot be recreated without the private key, so they get random ones."""
    for i in range(start, len(entries)):
        entries[i]["prev_hash"] = entries[i - 1]["hash"] if i else "0" * 64
        rehash(entries[i])
        entries[i]["sig"] = fake_sig()


def renumber(entries: list[dict]) -> None:
    for i, e in enumerate(entries, start=1):
        e["seq"] = i


def first_index(entries, pred, start=1):
    for i in range(start, len(entries)):
        if pred(entries[i]):
            return i
    return None


def other_code(codes: list[str], current: str | None) -> str:
    return next(c for c in codes if c != current)


# ---------------------------------------------------------------- attacks

def build_attacks(orig: list[dict], codes: list[str]) -> list[tuple[str, str, list[dict]]]:
    """Return (name, description, manipulated entries)."""
    n = len(orig)
    mid = n // 2                                         # an entry in the middle
    target = first_index(orig, lambda e: e["type"] in ("checkin", "checkout", "rejected")
                         and "code" in e["payload"]) or mid
    out = []

    def c():
        return copy.deepcopy(orig)

    e = c(); del e[mid]
    out.append(("delete_entry", f"entry seq {orig[mid]['seq']} removed", e))

    e = c(); del e[mid]; renumber(e); rechain(e, mid)
    out.append(("delete_and_rechain", f"seq {orig[mid]['seq']} removed, later entries renumbered and re-hashed", e))

    e = c(); old = e[target]["payload"].get("code"); e[target]["payload"]["code"] = other_code(codes, old)
    out.append(("change_code", f"seq {orig[target]['seq']}: code {old} -> {e[target]['payload']['code']}, hash untouched", e))

    e = c(); e[target]["payload"]["code"] = other_code(codes, old); rehash(e[target])
    out.append(("change_code_new_hash", f"seq {orig[target]['seq']}: code changed and hash recomputed (signature kept)", e))

    e = c(); e[target]["payload"]["code"] = other_code(codes, old); rechain(e, target)
    out.append(("change_code_rechain", f"seq {orig[target]['seq']}: code changed, whole rest of the chain re-hashed, random signatures", e))

    e = c(); e[target]["recorded_at"] = e[target]["recorded_at"][:11] + "03:00:00" + e[target]["recorded_at"][19:]
    out.append(("change_time", f"seq {orig[target]['seq']}: recorded_at changed", e))

    fake = copy.deepcopy(orig[target]); fake["type"] = "checkin"
    fake["payload"] = {"code": codes[-1], "source": {"kind": "station"}}
    e = c(); e.insert(mid, fake); renumber(e); rechain(e, mid)
    out.append(("insert_fake_middle", f"fake check-in of {codes[-1]} inserted at seq {mid + 1}, rest renumbered and re-hashed", e))

    fake2 = copy.deepcopy(fake); fake2["seq"] = n + 1; fake2["prev_hash"] = orig[-1]["hash"]
    rehash(fake2); fake2["sig"] = fake_sig()
    e = c() + [fake2]
    out.append(("append_fake_end", f"fake check-in appended as seq {n + 1} with correct chain hash, random signature", e))

    fake3 = copy.deepcopy(orig[mid]); fake3["payload"] = {"code": codes[-1], "source": {"kind": "station"}}
    rehash(fake3); fake3["sig"] = fake_sig()
    e = c(); e.insert(mid + 1, fake3)
    out.append(("fake_same_seq", f"second, different entry with seq {orig[mid]['seq']} inserted", e))

    e = c(); e.insert(mid + 1, copy.deepcopy(orig[mid]))
    out.append(("duplicate_entry", f"seq {orig[mid]['seq']} appears twice (identical)", e))

    e = c(); e[mid], e[mid + 1] = e[mid + 1], e[mid]
    out.append(("swap_entries", f"seq {orig[mid]['seq']} and {orig[mid + 1]['seq']} swapped", e))

    e = c()[:-1]
    out.append(("truncate_last", "last entry (the handover) cut off", e))

    e = c()[: max(2, n // 2)]
    out.append(("truncate_half", f"log cut after seq {max(2, n // 2)}", e))

    # whole log re-signed with an attacker's own key (also the genesis public key replaced)
    k = crypto.generate_private_key()
    e = c(); e[0]["payload"]["station_pubkey"] = crypto.public_key_b64(k)
    e[target]["payload"]["code"] = other_code(codes, old)
    rebuilt = []
    for x in e:
        body = crypto.entry_body(x)
        body["prev_hash"] = rebuilt[-1]["hash"] if rebuilt else "0" * 64
        rebuilt.append(crypto.seal(body, k))
    out.append(("resign_with_other_key", "code changed, then the WHOLE log re-signed with an attacker's own key", rebuilt))
    return out


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir"); ap.add_argument("--mode", choices=["live", "rehearsal"])
    ap.add_argument("--file", help="log to attack (default: the log in the data dir)")
    ap.add_argument("--out", default="attack_b_out", help="folder for the manipulated copies")
    ap.add_argument("--server", action="store_true", help="also send every copy to POST /v1/check (dry run)")
    args = ap.parse_args()

    ov = {}
    if args.data_dir:
        ov["data_dir"] = Path(args.data_dir)
    if args.mode:
        os.environ["RESQ_MODE"] = args.mode
    cfg = load_config(**ov)

    log_path = Path(args.file) if args.file else cfg.log_path
    entries = [json.loads(l) for l in log_path.read_bytes().split(b"\n") if l.strip()]
    if len(entries) < 4:
        sys.exit(f"{log_path} has only {len(entries)} entries. Do a few check-ins first (need at least 4).")
    pub = entries[0]["payload"]["station_pubkey"]
    codes = sorted(load_codelist(cfg.codelist_path))

    note = ""
    if entries[-1]["type"] != "handover":
        # Simulate what the upload does: append a signed handover - ON THE COPY ONLY.
        ks = KeyStore(cfg.key_path)
        if not ks.exists():
            sys.exit("Log does not end with a handover and no station key found to simulate one.")
        h = {"v": 1, "station_id": entries[-1]["station_id"], "seq": entries[-1]["seq"] + 1,
             "type": "handover", "recorded_at": entries[-1]["recorded_at"],
             "payload": {"last_seq": entries[-1]["seq"] + 1, "count": len(entries) + 1},
             "prev_hash": entries[-1]["hash"]}
        entries.append(crypto.seal(h, ks.load()))
        note = "(a handover was added to the copy only, as the upload would do; the real log is unchanged)"

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "00_original.jsonl").write_bytes(dump(entries))

    api = ApiClient(cfg.api_base, cfg.team_token) if args.server else None
    if api and not cfg.team_token:
        sys.exit("--server needs RESQ_TEAM_TOKEN in .env")

    def run(data: bytes):
        rep = verify_log(data.split(b"\n"), expected_pubkey_b64=pub, codes=set(codes))
        local = sorted(rep.codes())
        srv = None
        if api:
            try:
                body = api.check(data).body
                srv = sorted({f["code"] for f in body.get("findings", [])}) or ["(none)"]
            except ApiError as exc:
                srv = [f"HTTP {exc.status}: {exc}"]
        return rep, local, srv

    print(f"Log: {log_path}  ({len(entries)} entries, station {entries[0]['station_id']}) {note}\n")
    base_rep, base_codes, base_srv = run(dump(entries))
    print(f"{'ORIGINAL':24} {'OK' if base_rep.ok and base_rep.ends_with_handover else 'PROBLEM':10} local: {', '.join(base_codes) or '(none)'}"
          + (f" | server: {', '.join(base_srv)}" if api else ""))
    if not base_rep.ok:
        print("\nThe ORIGINAL log already has errors - fix that first; the attack results below are meaningless.")
    print("-" * 100)

    missed = 0
    for i, (name, desc, ents) in enumerate(build_attacks(entries, codes), start=1):
        data = dump(ents)
        (out_dir / f"{i:02d}_{name}.jsonl").write_bytes(data)
        rep, local, srv = run(data)
        new = [c for c in local if c not in base_codes or c.startswith("E_")]
        detected = bool(new)
        missed += not detected
        print(f"{name:24} {'DETECTED' if detected else 'MISSED !!':10} local: {', '.join(local) or '(none)'}"
              + (f" | server: {', '.join(srv)}" if api else ""))
        print(f"{'':35}{desc}")

    print("-" * 100)
    print(f"Copies saved in {out_dir.resolve()}")
    if missed:
        print(f"{missed} manipulation(s) NOT detected - see notes in docs/threat-model.md (e.g. cutting at an older handover).")
    else:
        print("All manipulations detected.")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
