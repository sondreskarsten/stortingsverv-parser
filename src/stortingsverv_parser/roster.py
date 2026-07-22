"""Attach Stortinget API identity (person id, date of birth) to parsed persons.

The register prints names; downstream joins need (name, foedselsdato). The
reference pool is the raw representanter responses (fast plus vara) for
every parliamentary period 2001-2029 and the current regjering response,
committed verbatim under backfill/stortinget_api/. Matching is by printed
name against the pool: exact "Etternavn, Fornavn" first, then surname plus
first given-name token, requiring uniqueness at each step. Ambiguous and
unmatched rows are flagged, never guessed. The historical regjering
endpoint ignores its period parameter and returns only the sitting
government, so ministers who never sat in parliament may stay unmatched.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa

_DOTNET_DATE_RE = re.compile(r"/Date\((-?\d+)[+-]\d{4}\)/")

ROSTER_SCHEMA = pa.schema(
    [
        ("date", pa.string()),
        ("person_index", pa.int32()),
        ("section_heading", pa.string()),
        ("person_header", pa.string()),
        ("name", pa.string()),
        ("party", pa.string()),
        ("constituency", pa.string()),
        ("api_person_id", pa.string()),
        ("etternavn", pa.string()),
        ("fornavn", pa.string()),
        ("foedselsdato", pa.string()),
        ("kjoenn", pa.string()),
        ("match_method", pa.string()),
    ]
)


def _dotnet_date(s: str | None) -> str | None:
    if not s:
        return None
    m = _DOTNET_DATE_RE.match(s)
    if not m:
        return None
    dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", " ".join(s.split())).casefold()


def load_reference(api_dir: Path) -> list[dict]:
    people: dict[str, dict] = {}
    for f in sorted(api_dir.glob("representanter_*.json")):
        data = json.loads(f.read_text())
        for raw in data.get("representanter_liste", []):
            pid = raw.get("id", "")
            rec = people.setdefault(
                pid,
                {
                    "api_person_id": pid,
                    "etternavn": raw.get("etternavn", ""),
                    "fornavn": raw.get("fornavn", ""),
                    "foedselsdato": _dotnet_date(raw.get("foedselsdato")),
                    "kjoenn": raw.get("kjoenn"),
                    "sources": [],
                },
            )
            rec["sources"].append(f.stem)
    for f in sorted(api_dir.glob("regjering_*.json")):
        data = json.loads(f.read_text())
        key = next((k for k in data if k.endswith("_liste")), None)
        for raw in data.get(key, []) if key else []:
            pid = raw.get("id", "")
            if pid in people:
                people[pid]["sources"].append(f.stem)
                continue
            people[pid] = {
                "api_person_id": pid,
                "etternavn": raw.get("etternavn", ""),
                "fornavn": raw.get("fornavn", ""),
                "foedselsdato": _dotnet_date(raw.get("foedselsdato")),
                "kjoenn": raw.get("kjoenn"),
                "sources": [f.stem],
            }
    return list(people.values())


def _token_set(name: str) -> frozenset[str]:
    return frozenset(_norm(name).replace(",", " ").replace("-", " ").split())


def _index(reference: list[dict]) -> tuple[dict, dict, dict]:
    exact: dict[str, list[dict]] = {}
    loose: dict[tuple[str, str], list[dict]] = {}
    tokens: dict[frozenset[str], list[dict]] = {}
    for r in reference:
        full = f"{r['etternavn']}, {r['fornavn']}"
        exact.setdefault(_norm(full), []).append(r)
        first = r["fornavn"].split()[0] if r["fornavn"].split() else ""
        loose.setdefault((_norm(r["etternavn"]), _norm(first)), []).append(r)
        tokens.setdefault(_token_set(full), []).append(r)
    return exact, loose, tokens


def _unique_by_identity(cands: list[dict]) -> dict | None:
    idents = {(c["foedselsdato"], _norm(c["etternavn"]), _norm(c["fornavn"])) for c in cands}
    if len(idents) == 1:
        return cands[0]
    return None


def build_roster(persons: list[dict], reference: list[dict]) -> pa.Table:
    exact, loose, tokens = _index(reference)
    rows: list[dict] = []
    for p in persons:
        name = p["name"]
        hit = None
        method = "unmatched"
        cands = exact.get(_norm(name), [])
        if cands:
            hit = _unique_by_identity(cands)
            method = "exact" if hit else "ambiguous"
        if hit is None and method != "ambiguous" and "," in name:
            etter, forn = name.split(",", 1)
            first = forn.split()[0] if forn.split() else ""
            cands = loose.get((_norm(etter), _norm(first)), [])
            if cands:
                hit = _unique_by_identity(cands)
                method = "surname_first_token" if hit else "ambiguous"
        if hit is None and method != "ambiguous":
            cands = tokens.get(_token_set(name), [])
            if cands:
                hit = _unique_by_identity(cands)
                method = "token_set" if hit else "ambiguous"
        rows.append(
            {
                "date": p["date"],
                "person_index": p["person_index"],
                "section_heading": p["section_heading"],
                "person_header": p["person_header"],
                "name": name,
                "party": p["party"],
                "constituency": p["constituency"],
                "api_person_id": hit["api_person_id"] if hit else None,
                "etternavn": hit["etternavn"] if hit else None,
                "fornavn": hit["fornavn"] if hit else None,
                "foedselsdato": hit["foedselsdato"] if hit else None,
                "kjoenn": str(hit["kjoenn"]) if hit and hit.get("kjoenn") is not None else None,
                "match_method": method,
            }
        )
    return pa.Table.from_pylist(rows, schema=ROSTER_SCHEMA)
