"""RESQ station administration CLI.

    python manage.py key-show                      public key + station id
    python manage.py key-import --seed-hex HEX     import your ALREADY REGISTERED key
    python manage.py key-import --pem FILE         (or --seed-b64 / --json FILE)
    python manage.py key-generate                  only for a NEW, not yet registered station
    python manage.py init --station-id ST-T1       write genesis (start of the live log)
    python manage.py verify [--file F]             offline verification of a log
    python manage.py health | check | status | findings | events
    python manage.py upload --yes                  handover + upload (live mode only)
    python manage.py backup --out DIR              copy log + metadata (no private key)

Stop the web app before running commands that write (init, upload): only one writer is allowed.
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from backend import crypto
from backend.station import Station, load_codelist
from backend.storage import KeyStore, LockError, StorageError
from backend.sync import ApiClient, ApiError, check_remote, upload
from backend.validation import verify_log
from config import load_config


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _open(cfg, lock=True):
    try:
        return Station.open(cfg, acquire_lock=lock)
    except LockError as exc:
        sys.exit(f"ERROR: {exc}")


def cmd_key_show(cfg, args):
    ks = KeyStore(cfg.key_path)
    if not ks.exists():
        sys.exit(f"No key at {cfg.key_path}")
    st = _open(cfg, lock=False)
    _print({"public_key_b64": ks.public_key_b64(), "station_id": st.station_id, "data_dir": str(cfg.data_dir),
            "mode": cfg.mode})


def _seed_from_args(args) -> bytes:
    if args.seed_hex:
        return bytes.fromhex(args.seed_hex.strip())
    if args.seed_b64:
        raw = base64.b64decode(args.seed_b64.strip())
        return raw[:32] if len(raw) == 64 else raw  # accept 64-byte seed||pub form
    if args.pem:
        from cryptography.hazmat.primitives import serialization
        key = serialization.load_pem_private_key(Path(args.pem).read_bytes(), password=None)
        return crypto.seed_bytes(key)
    if args.json:
        d = json.loads(Path(args.json).read_text(encoding="utf-8"))
        for k in ("seed_hex", "private_key_hex", "private_hex"):
            if k in d:
                return bytes.fromhex(d[k])
        for k in ("seed_b64", "private_key_b64", "private_b64"):
            if k in d:
                raw = base64.b64decode(d[k])
                return raw[:32] if len(raw) == 64 else raw
        sys.exit("JSON key file needs seed_hex / private_key_hex / seed_b64 / private_key_b64")
    sys.exit("Give one of --seed-hex, --seed-b64, --pem, --json")


def cmd_key_import(cfg, args):
    seed = _seed_from_args(args)
    key = crypto.private_key_from_seed(seed)
    pub = crypto.public_key_b64(key)
    if args.expect_pub and args.expect_pub.strip() != pub:
        sys.exit(f"ERROR: imported key has public key {pub}, not the expected {args.expect_pub}")
    try:
        KeyStore(cfg.key_path).save_new(key, note="Imported registered station key. PRIVATE.")
    except StorageError as exc:
        sys.exit(f"ERROR: {exc}")
    print(f"Imported. Public key: {pub}\nCompare it with the key you registered with the organisers.")


def cmd_key_generate(cfg, args):
    if cfg.mode == "live" and not args.new_station:
        sys.exit("Refusing: in LIVE mode a key is generated only with --new-station "
                 "(you have already registered a key; import it with key-import instead).")
    try:
        pub = KeyStore(cfg.key_path).save_new(crypto.generate_private_key())
    except StorageError as exc:
        sys.exit(f"ERROR: {exc}")
    print(f"New key generated. Public key: {pub}")


def cmd_register_key(cfg, args):
    if not args.confirm_replace:
        sys.exit("Refusing. Registering again REPLACES the key the organisers have for your team "
                 "(only possible before the deadline and before any upload). Re-run with "
                 "--confirm-replace if you really mean it.")
    api = ApiClient(cfg.api_base, cfg.team_token)
    pub = KeyStore(cfg.key_path).public_key_b64()
    try:
        res = api.register_key(pub)
    except ApiError as exc:
        sys.exit(f"ERROR {exc.status}: {exc}")
    _print(res.body)


def cmd_init(cfg, args):
    st = _open(cfg)
    try:
        e = st.initialise(args.station_id, args.team_id or cfg.team_id)
    except Exception as exc:
        sys.exit(f"ERROR: {exc}")
    print(f"Genesis written: {e['station_id']} seq {e['seq']} at {e['recorded_at']}")


def cmd_verify(cfg, args):
    codes = None
    try:
        codes = set(load_codelist(cfg.codelist_path))
    except Exception:
        pass
    if args.file:
        lines = Path(args.file).read_bytes().split(b"\n")
        pub = args.pubkey
    else:
        st = _open(cfg, lock=False)
        lines = st.log.lines()
        pub = args.pubkey or st.meta.get("public_key_b64")
    rep = verify_log(lines, expected_pubkey_b64=pub, codes=codes)
    _print(rep.as_dict())
    sys.exit(0 if rep.ok else 1)


def _api(cfg):
    return ApiClient(cfg.api_base, cfg.team_token)


def _call(fn):
    try:
        _print(fn())
    except ApiError as exc:
        _print({"error": str(exc), "status": exc.status, "body": exc.body})
        sys.exit(1)


def cmd_health(cfg, args):
    _call(lambda: _api(cfg).health().body)


def cmd_check(cfg, args):
    if args.file:
        _call(lambda: _api(cfg).check(Path(args.file).read_bytes()).body)
    else:
        st = _open(cfg, lock=False)
        _call(lambda: check_remote(st, _api(cfg)))


def cmd_status(cfg, args):
    _call(lambda: _api(cfg).status().body)


def cmd_findings(cfg, args):
    _call(lambda: _api(cfg).findings().body)


def cmd_events(cfg, args):
    _call(lambda: _api(cfg).events(args.from_seq, args.limit).body)


def cmd_upload(cfg, args):
    if not args.yes:
        sys.exit("Upload counts for scoring. Re-run with --yes to confirm.")
    st = _open(cfg)
    _call(lambda: upload(st, _api(cfg)))


def cmd_backup(cfg, args):
    out = Path(args.out) / f"resq-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    for p in (cfg.log_path, cfg.station_path, cfg.sync_path):
        if p.exists():
            shutil.copy2(p, out / p.name)
    print(f"Backup written to {out} (private key NOT included)")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", help="override RESQ_DATA_DIR")
    ap.add_argument("--mode", choices=["live", "rehearsal"], help="override RESQ_MODE")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("key-show").set_defaults(fn=cmd_key_show)
    p = sub.add_parser("key-import")
    p.add_argument("--seed-hex"); p.add_argument("--seed-b64"); p.add_argument("--pem"); p.add_argument("--json")
    p.add_argument("--expect-pub", help="the public key you registered; import aborts if it differs")
    p.set_defaults(fn=cmd_key_import)
    p = sub.add_parser("key-generate"); p.add_argument("--new-station", action="store_true")
    p.set_defaults(fn=cmd_key_generate)
    p = sub.add_parser("register-key"); p.add_argument("--confirm-replace", action="store_true")
    p.set_defaults(fn=cmd_register_key)
    p = sub.add_parser("init"); p.add_argument("--station-id", required=True); p.add_argument("--team-id")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("verify"); p.add_argument("--file"); p.add_argument("--pubkey")
    p.set_defaults(fn=cmd_verify)
    sub.add_parser("health").set_defaults(fn=cmd_health)
    p = sub.add_parser("check"); p.add_argument("--file"); p.set_defaults(fn=cmd_check)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("findings").set_defaults(fn=cmd_findings)
    p = sub.add_parser("events"); p.add_argument("--from-seq", type=int, default=1)
    p.add_argument("--limit", type=int, default=500); p.set_defaults(fn=cmd_events)
    p = sub.add_parser("upload"); p.add_argument("--yes", action="store_true"); p.set_defaults(fn=cmd_upload)
    p = sub.add_parser("backup"); p.add_argument("--out", required=True); p.set_defaults(fn=cmd_backup)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    overrides = {}
    if args.data_dir:
        overrides["data_dir"] = args.data_dir
    cfg = load_config(**overrides)
    if args.mode:
        cfg.mode = args.mode
    args.fn(cfg, args)


if __name__ == "__main__":
    main()
