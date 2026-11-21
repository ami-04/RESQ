"""Canonical JSON, SHA-256 hashing and Ed25519 signing (FORMAT.md section 5).

This module is deliberately small and dependency-free apart from `cryptography`.
Everything here must match the organiser's reference implementation byte for byte:

    canonical(d) = json.dumps(d, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False).encode("utf-8")
    hash = sha256(canonical(entry without hash/sig)).hexdigest()
    sig  = base64(ed25519_sign(bytes.fromhex(hash)))
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

GENESIS_PREV_HASH = "0" * 64

# Public test key from testfaelle/testschluessel.json. Must NEVER be used for a station.
PUBLIC_TEST_KEY_B64 = "DRbIanEOvzSCXwinI2eOpu6b0+r92HnETtgZuoJ5vLg="


def canonical(d: Any) -> bytes:
    """Canonical serialisation exactly as in FORMAT.md section 5."""
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_body(entry: dict) -> dict:
    """The entry without `hash` and `sig` (the part that is hashed)."""
    return {k: v for k, v in entry.items() if k not in ("hash", "sig")}


def compute_hash(entry: dict) -> str:
    return hashlib.sha256(canonical(entry_body(entry))).hexdigest()


# --------------------------------------------------------------------------- keys

def private_key_from_seed(seed: bytes) -> Ed25519PrivateKey:
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must be exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def seed_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def public_key_from_b64(pub_b64: str) -> Ed25519PublicKey:
    raw = base64.b64decode(pub_b64, validate=True)
    if len(raw) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


# --------------------------------------------------------------------------- sign / verify

def sign_hash(private_key: Ed25519PrivateKey, hash_hex: str) -> str:
    """Sign the 32 RAW bytes of the SHA-256 digest (not the hex text)."""
    digest = bytes.fromhex(hash_hex)
    if len(digest) != 32:
        raise ValueError("hash must be 32 bytes / 64 hex characters")
    return base64.b64encode(private_key.sign(digest)).decode("ascii")


def seal(entry: dict, private_key: Ed25519PrivateKey) -> dict:
    """Return a copy of `entry` with `hash` and `sig` set."""
    out = entry_body(entry)
    out["hash"] = compute_hash(out)
    out["sig"] = sign_hash(private_key, out["hash"])
    return out


def verify_signature(public_key: Ed25519PublicKey, hash_hex: str, sig_b64: str) -> bool:
    try:
        sig = base64.b64decode(sig_b64, validate=True)
        public_key.verify(sig, bytes.fromhex(hash_hex))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
