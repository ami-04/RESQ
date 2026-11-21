"""Smart volunteer finder: English/German skill search over people on site (read-only)."""
import pytest

from backend import finder
from backend import registration as reg

# code list (data/codeliste.json): 3NW-4UJ Rettungsschwimmerin · 84M-6GV Statiker · D7B-QQY Pflegefachkraft
# ECW-8CB Notfallsanitäterin · JKN-ERF Lkw-Fahrer (Führerschein CE) · MSF-9DA Elektriker · WKW-DJW Koch
# ACZ-GXK Erzieherin · 9MF-SVJ (no skill)


@pytest.fixture
def busy(station):
    for c in ("3NW-4UJ", "84M-6GV", "D7B-QQY", "ECW-8CB", "JKN-ERF", "MSF-9DA", "WKW-DJW", "ACZ-GXK", "9MF-SVJ"):
        assert reg.checkin(station, c).status == "success"
    assert reg.walkin(station, name="Lena", role="gelb", skill="Nurse (ICU)", consent=True).status == "success"
    assert reg.walkin(station, name="Tom", role="rot", skill="electrician", consent=True).status == "success"
    assert reg.walkin(station, name="Ana", role="gruen", skill="", consent=True).status == "success"
    return station


def ids(res):
    return {p["id"] for p in res["results"]}


@pytest.mark.parametrize("query,expected", [
    ("nurse", {"D7B-QQY", "W-T9-0001"}),
    ("Pflege", {"D7B-QQY", "W-T9-0001"}),
    ("Krankenschwester", {"D7B-QQY", "W-T9-0001"}),
    ("electrician", {"MSF-9DA", "W-T9-0002"}),
    ("Elektriker", {"MSF-9DA", "W-T9-0002"}),
    ("strom", {"MSF-9DA", "W-T9-0002"}),
    ("lifeguard", {"3NW-4UJ"}),
    ("Rettungsschwimmer", {"3NW-4UJ"}),
    ("paramedic", {"ECW-8CB"}),
    ("Sanitäter", {"ECW-8CB"}),
    ("structural engineer", {"84M-6GV"}),
    ("Statiker", {"84M-6GV"}),
    ("truck driver", {"JKN-ERF"}),
    ("LKW", {"JKN-ERF"}),
    ("Führerschein", {"JKN-ERF"}),
    ("cook", {"WKW-DJW"}),
    ("Köchin", {"WKW-DJW"}),
    ("teacher", {"ACZ-GXK"}),
    ("Kita", {"ACZ-GXK"}),
])
def test_english_and_german_queries_find_the_same_people(busy, query, expected):
    assert ids(finder.search(busy, query)) == expected


def test_medical_umbrella_finds_nurses_and_paramedics(busy):
    assert ids(finder.search(busy, "medical")) == {"D7B-QQY", "W-T9-0001", "ECW-8CB"}
    assert ids(finder.search(busy, "Erste Hilfe")) == {"D7B-QQY", "W-T9-0001", "ECW-8CB"}


def test_short_words_do_not_match_inside_other_words(busy):
    assert ids(finder.search(busy, "it")) == set()          # not inside "Statiker" / "Elektriker"
    assert ids(finder.search(busy, "chef")) == {"WKW-DJW"}   # chef -> cook / Koch
    assert ids(finder.search(busy, "ce")) == set()           # 2 letters, no skill group: too short to search
    assert ids(finder.search(busy, "car")) == set()         # 3 letters: whole words only


def test_role_filter_and_role_words(busy):
    assert ids(finder.search(busy, "", role="rot")) == {"84M-6GV", "ECW-8CB", "MSF-9DA", "W-T9-0002"}
    assert ids(finder.search(busy, "electrician", role="gelb")) == set()
    assert ids(finder.search(busy, "red electrician")) == {"MSF-9DA", "W-T9-0002"}


def test_empty_query_lists_everyone_on_site(busy):
    assert finder.search(busy, "")["count"] == 12


def test_walkin_skills_are_marked_claimed_and_code_list_skills_are_not(busy):
    res = {p["id"]: p for p in finder.search(busy, "nurse")["results"]}
    assert res["W-T9-0001"]["claimed"] is True and res["W-T9-0001"]["name"] == "Lena"
    assert res["D7B-QQY"]["claimed"] is False


def test_only_people_on_site_and_off_site_count_without_codes(busy):
    assert reg.checkout(busy, "MSF-9DA").status == "success"
    res = finder.search(busy, "Elektriker")
    assert ids(res) == {"W-T9-0002"}
    assert res["off_site_count"] == 1
    assert "MSF-9DA" not in str(res)                     # off-site codes are never revealed


def test_free_text_still_matches_unknown_skills(busy):
    assert reg.walkin(busy, name="Ben", role="gruen", skill="Imker", consent=True).status == "success"
    assert ids(finder.search(busy, "imker")) == {"W-T9-0004"}


def test_finder_never_writes_to_the_log(busy):
    n = len(busy.log)
    for q in ("nurse", "", "xyz", "rot"):
        finder.search(busy, q)
    assert len(busy.log) == n


def test_finder_http_endpoint_and_lan_block(busy):
    from app import create_app
    from backend.sync import ApiClient
    app = create_app(busy.cfg, station=busy, api=ApiClient("https://example.invalid", None))
    c = app.test_client()
    r = c.get("/api/finder?q=Pflege")
    assert r.status_code == 200 and {p["id"] for p in r.json["results"]} == {"D7B-QQY", "W-T9-0001"}
    assert r.json["group_labels"]["nurse"]["de"] == "Pflege"
    assert c.get("/api/finder?q=x", environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403


QUICK = {  # quick-search buttons: (English label, German label) -> expected people
    ("Medical", "Medizin"): {"D7B-QQY", "W-T9-0001", "ECW-8CB"},
    ("Electrician", "Elektriker"): {"MSF-9DA", "W-T9-0002"},
    ("Driver", "Fahrer"): {"JKN-ERF"},
    ("Structural engineer", "Statiker"): {"84M-6GV"},
    ("Cook", "Koch"): {"WKW-DJW"},
    ("Childcare", "Kinderbetreuung"): {"ACZ-GXK"},
    ("Lifeguard", "Rettungsschwimmer"): {"3NW-4UJ"},
}


@pytest.mark.parametrize("labels,expected", list(QUICK.items()))
def test_quick_buttons_work_in_both_languages(busy, labels, expected):
    for label in labels:
        assert ids(finder.search(busy, label)) == expected, label


def test_quick_button_labels_match_the_page():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "i18n.js").read_text(encoding="utf-8")
    for en, de in QUICK:
        assert f'"{en}"' in js and f'"{de}"' in js
