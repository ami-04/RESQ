import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import crypto  # noqa: E402
from backend.station import Station  # noqa: E402
from backend.storage import KeyStore  # noqa: E402
from config import load_config  # noqa: E402

TESTFAELLE = ROOT / "testfaelle"
VALID_CODES = ["3NW-4UJ", "84M-6GV", "9MF-SVJ", "ACZ-GXK"]


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for var in ("RESQ_TEAM_TOKEN", "RESQ_DATA_DIR", "RESQ_MODE", "RESQ_STATION_ID", "RESQ_WALKIN_START"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("RESQ_TEAM_TOKEN", "")
    c = load_config(data_dir=tmp_path / "data")
    c.codelist_path = ROOT / "data" / "codeliste.json"
    c.team_token = None
    c.mode = "live"
    return c


@pytest.fixture
def station(cfg):
    KeyStore(cfg.key_path).save_new(crypto.generate_private_key())
    st = Station.open(cfg)
    st.initialise("ST-T9")
    yield st
    st.close()


def reopen(st: Station) -> Station:
    cfg = st.cfg
    st.close()
    return Station.open(cfg)


@pytest.fixture
def t1_lines():
    return (TESTFAELLE / "T1_gueltig.jsonl").read_bytes().split(b"\n")


@pytest.fixture
def t1_key():
    return json.loads((TESTFAELLE / "testschluessel.json").read_text())
