"""Smart volunteer finder: who is ON SITE right now with a given skill?

Read-only: never writes to the log. Search works in English and German: a query is
expanded through skill groups (e.g. "nurse" also finds "Pflegefachkraft", and "Elektriker"
also finds a walk-in who typed "electrician").

Walk-in skills are self-declared ("claimed"); skills from the organisers' code list are "listed".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ROLE_ORDER = {"rot": 0, "gelb": 1, "gruen": 2}
ROLE_WORDS = {
    "rot": "rot", "red": "rot", "gelb": "gelb", "yellow": "gelb", "gruen": "gruen", "green": "gruen",
}
STOPWORDS = {"a", "an", "the", "and", "or", "for", "with", "of", "der", "die", "das", "und", "oder",
             "fuer", "mit", "ein", "eine", "einen", "von", "person", "someone", "jemand", "need", "brauche"}


def norm(s: str) -> str:
    """lower case, German umlauts spelled out, accents removed, punctuation -> space."""
    s = (s or "").lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


@dataclass(frozen=True)
class Group:
    id: str
    en: str
    de: str
    terms: tuple[str, ...]          # normalised; "=word" means whole word only
    includes: tuple[str, ...] = ()  # umbrella groups pull in other groups


GROUPS: tuple[Group, ...] = (
    Group("nurse", "Nursing / care", "Pflege",
          ("nurse", "nursing", "caregiver", "carer", "pflege", "pfleger", "krankenpfleg", "krankenschwester",
           "altenpfleg", "pflegefachkraft")),
    Group("paramedic", "Paramedic / ambulance", "Rettungsdienst / Sanitäter",
          ("paramedic", "=emt", "ambulance", "=medic", "sanitaeter", "notfallsanitaeter", "rettungssanitaeter",
           "rettungsdienst", "rettungsassistent", "ersthelfer")),
    Group("doctor", "Doctor", "Arzt / Ärztin",
          ("doctor", "physician", "=gp", "surgeon", "arzt", "aerzt", "notarzt", "mediziner", "chirurg")),
    Group("medical", "Medical (all)", "Medizin (alle)",
          ("medical", "medicine", "health", "first aid", "erste hilfe", "medizin", "gesundheit", "sanitaets"),
          includes=("nurse", "paramedic", "doctor")),
    Group("lifeguard", "Lifeguard / water rescue", "Rettungsschwimmer / Wasserrettung",
          ("lifeguard", "life guard", "swimmer", "swimming", "water rescue", "rettungsschwimm", "schwimm",
           "wasserrett", "=dlrg")),
    Group("structural", "Structural / civil engineer", "Statiker / Bauingenieur",
          ("structural", "civil engineer", "engineer", "building inspector", "statik", "statiker",
           "bauingenieur", "ingenieur", "tragwerk")),
    Group("childcare", "Childcare / teacher", "Erziehung / Lehrkraft",
          ("childcare", "child care", "teacher", "educator", "kindergarten", "nanny", "children", "kids",
           "erzieh", "kinderbetreu", "lehrer", "paedagog", "=kita", "tagesmutter")),
    Group("driver", "Driver / truck licence", "Fahrer / Führerschein",
          ("driver", "driving", "truck", "lorry", "=hgv", "licence", "license", "bus driver", "fahrer",
           "=lkw", "fuehrerschein", "kraftfahrer", "berufskraftfahrer", "transport")),
    Group("electrician", "Electrician / power", "Elektriker / Strom",
          ("electrician", "electrical", "electric", "electricity", "power", "generator", "elektrik",
           "elektriker", "elektro", "strom", "elektroniker", "stromaggregat")),
    Group("cook", "Cook / kitchen", "Koch / Küche",
          ("cook", "=chef", "kitchen", "catering", "food", "meals", "=koch", "kochen", "koechin", "kueche",
           "verpflegung", "essen")),
    Group("fire", "Firefighter", "Feuerwehr",
          ("firefighter", "fire fighter", "fire brigade", "fireman", "feuerwehr", "brandschutz")),
    Group("security", "Police / security", "Polizei / Sicherheit",
          ("police", "security", "guard", "polizei", "sicherheit", "ordner", "wachdienst")),
    Group("plumber", "Plumber / water supply", "Installateur / Wasser",
          ("plumber", "plumbing", "pipes", "installateur", "klempner", "sanitaerinstall", "wasserversorgung")),
    Group("mechanic", "Mechanic", "Mechaniker",
          ("mechanic", "mechanical", "mechanik", "mechaniker", "=kfz", "mechatroni")),
    Group("craft", "Carpenter / craftsperson", "Handwerk / Tischler",
          ("carpenter", "joiner", "craftsman", "craftsperson", "handyman", "builder", "construction",
           "tischler", "schreiner", "zimmerer", "zimmermann", "handwerk", "maurer", "bauarbeiter")),
    Group("it", "IT / radio / communications", "IT / Funk / Kommunikation",
          ("=it", "computer", "network", "radio", "ham radio", "communications", "telecom", "funk", "funker",
           "amateurfunk", "informatik", "netzwerk", "=edv")),
    Group("language", "Interpreter / translator", "Dolmetscher / Übersetzer",
          ("interpreter", "translator", "translation", "dolmetsch", "uebersetz")),
    Group("psych", "Psychological support", "Psychologische Hilfe",
          ("psycholog", "counselor", "counsellor", "crisis", "social worker", "therapist", "seelsorge",
           "krisenintervention", "sozialarbeit", "therapeut")),
    Group("logistics", "Logistics / warehouse", "Logistik / Lager",
          ("logistics", "warehouse", "forklift", "logistik", "=lager", "lagerist", "stapler", "gabelstapler")),
)
_BY_ID = {g.id: g for g in GROUPS}


def _whole(term: str) -> tuple[bool, str]:
    return (True, term[1:]) if term.startswith("=") else (len(term) <= 3, term)


def _query_hits_term(q: str, term: str) -> bool:
    whole, t = _whole(term)
    if whole or len(q) <= 3:
        return q == t
    return t.startswith(q) or q.startswith(t)


def _text_has_term(text: str, term: str) -> bool:
    whole, t = _whole(term)
    if whole:
        return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text) is not None
    return t in text


def _expand(group_ids: set[str]) -> set[str]:
    out = set(group_ids)
    for gid in group_ids:
        out.update(_BY_ID[gid].includes)
    return out


def groups_for(query: str) -> tuple[set[str], list[str]]:
    """Return (matched group ids, leftover tokens that matched no group)."""
    q = norm(query)
    hits = {g.id for g in GROUPS if any(_query_hits_term(q, t) for t in g.terms)} if " " in q else set()
    leftovers = []
    for tok in q.split():
        if tok in STOPWORDS or tok in ROLE_WORDS:
            continue
        found = {g.id for g in GROUPS if any(_query_hits_term(tok, t) for t in g.terms)}
        hits |= found
        if not found:
            leftovers.append(tok)
    return _expand(hits), leftovers


def _role_from_query(query: str) -> str | None:
    roles = {ROLE_WORDS[t] for t in norm(query).split() if t in ROLE_WORDS}
    return roles.pop() if len(roles) == 1 else None


def person_matches(text: str, group_ids: set[str], leftovers: list[str]) -> list[str]:
    """Which groups (or 'text') make this person's skill/name text match."""
    why = [gid for gid in sorted(group_ids) if any(_text_has_term(text, t) for t in _BY_ID[gid].terms)]
    if any(len(tok) >= 3 and tok in text for tok in leftovers):
        why.append("text")
    return why


def search(st, query: str = "", role: str = "") -> dict:
    """People currently on site matching query (skill, EN/DE) and optional role."""
    role = role if role in ROLE_ORDER else (_role_from_query(query) or "")
    group_ids, leftovers = groups_for(query)
    has_terms = bool(group_ids or leftovers)

    def label(key):
        kind, value = key
        if kind == "code":
            info = st.codes.get(value, {})
            return {"id": value, "kind": "code", "name": "", "role": info.get("role", ""),
                    "skill": info.get("skill", ""), "claimed": False}
        w = st.state.walkins.get(value, {})
        return {"id": value, "kind": "walkin", "name": w.get("name", ""), "role": w.get("role", ""),
                "skill": w.get("skill", ""), "claimed": True}

    results = []
    for key, info in st.state.active.items():
        p = label(key)
        if role and p["role"] != role:
            continue
        if has_terms:
            why = person_matches(norm(f"{p['skill']} {p['name']}"), group_ids, leftovers)
            if not why:
                continue
            p["matched"] = why
        else:
            p["matched"] = []
        p["since"] = info["since"]
        results.append(p)
    results.sort(key=lambda p: (-len(p["matched"]), ROLE_ORDER.get(p["role"], 9), p["skill"] == "", p["since"]))

    # How many people with this skill are on the code list but NOT here (count only: no codes shown).
    off_site = 0
    if has_terms:
        for code, info in st.codes.items():
            if ("code", code) in st.state.active or (role and info.get("role") != role):
                continue
            if person_matches(norm(info.get("skill", "")), group_ids, leftovers):
                off_site += 1

    return {"query": query, "role": role, "groups": sorted(group_ids),
            "group_labels": {g: {"en": _BY_ID[g].en, "de": _BY_ID[g].de} for g in sorted(group_ids)},
            "count": len(results), "results": results, "off_site_count": off_site}
