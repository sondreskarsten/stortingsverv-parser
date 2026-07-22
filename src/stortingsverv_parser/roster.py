"""Attach Stortinget API identity (person id, date of birth) to parsed persons.

The reference pool is the raw representanter responses (fast plus vara)
for every parliamentary period 1997-2029 and the current regjering
response, committed verbatim under backfill/stortinget_api/. The match
space was measured before the method hierarchy was chosen: exact full
names collide zero times in the pool, (full given name, dob) collides
twice, surname plus first given token eight times. Every method therefore
requires a unique surviving candidate; when several candidates share a
key, the row's printed constituency and party filter them before anything
is declared ambiguous. Confirmed surname changes (the register prints the
old name, the API holds only the current one) motivate the looser tail
methods. Nothing is ever guessed: unmatched and ambiguous rows stay
flagged.
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


def _tokens(s: str) -> list[str]:
    return _norm(s).replace(",", " ").replace("-", " ").split()


def load_reference(api_dir: Path) -> list[dict]:
    people: dict[str, dict] = {}

    def add(raw: dict, source: str, parti: str | None, fylke: str | None) -> None:
        pid = raw.get("id", "")
        rec = people.setdefault(
            pid,
            {
                "api_person_id": pid,
                "etternavn": raw.get("etternavn", ""),
                "fornavn": raw.get("fornavn", ""),
                "foedselsdato": _dotnet_date(raw.get("foedselsdato")),
                "kjoenn": str(raw["kjoenn"]) if raw.get("kjoenn") is not None else None,
                "partier": set(),
                "fylker": set(),
                "sources": [],
            },
        )
        rec["sources"].append(source)
        if parti:
            rec["partier"].add(_norm(parti))
        if fylke:
            rec["fylker"].add(_norm(fylke))

    for f in sorted(api_dir.glob("representanter_*.json")):
        for raw in json.loads(f.read_text()).get("representanter_liste", []):
            parti = (raw.get("parti") or {}).get("id")
            fylke = (raw.get("fylke") or {}).get("navn")
            add(raw, f.stem, parti, fylke)
    for f in sorted(api_dir.glob("regjering_*.json")):
        data = json.loads(f.read_text())
        key = next((k for k in data if k.endswith("_liste")), None)
        for raw in data.get(key, []) if key else []:
            add(raw, f.stem, None, None)
    return list(people.values())


def _unique_identity(cands: list[dict]) -> dict | None:
    idents = {
        (c["foedselsdato"], _norm(c["etternavn"]), _norm(c["fornavn"])) for c in cands
    }
    return cands[0] if len(idents) == 1 else None


def _context_filter(cands: list[dict], party: str | None, constituency: str | None):
    out = cands
    if constituency:
        narrowed = [c for c in out if _norm(constituency) in c["fylker"]]
        if narrowed:
            out = narrowed
    if party and len(out) > 1:
        narrowed = [c for c in out if _norm(party) in c["partier"]]
        if narrowed:
            out = narrowed
    return out


class _Matcher:
    def __init__(self, reference: list[dict]):
        self.exact: dict[str, list[dict]] = {}
        self.sur_first: dict[tuple[str, str], list[dict]] = {}
        self.token_set: dict[frozenset[str], list[dict]] = {}
        self.sur_token: dict[tuple[str, str], list[dict]] = {}
        self.maiden: dict[tuple[str, str], list[dict]] = {}
        self.fornavn: dict[str, list[dict]] = {}
        for r in reference:
            full = f"{r['etternavn']}, {r['fornavn']}"
            self.exact.setdefault(_norm(full), []).append(r)
            gtoks = _tokens(r["fornavn"])
            first = gtoks[0] if gtoks else ""
            self.sur_first.setdefault((_norm(r["etternavn"]), first), []).append(r)
            self.token_set.setdefault(frozenset(_tokens(full)), []).append(r)
            for st in _tokens(r["etternavn"]):
                self.sur_token.setdefault((st, first), []).append(r)
            for gt in gtoks:
                self.maiden.setdefault((gt, first), []).append(r)
            self.fornavn.setdefault(_norm(r["fornavn"]), []).append(r)

    def match(self, name: str, party: str | None, constituency: str | None):
        etter, _, forn = name.partition(",")
        forn = forn.strip()
        gtoks = _tokens(forn)
        first = gtoks[0] if gtoks else ""

        attempts: list[tuple[list[dict], str]] = [
            (self.exact.get(_norm(name), []), "exact"),
            (self.sur_first.get((_norm(etter), first), []), "surname_first_token"),
            (self.token_set.get(frozenset(_tokens(name)), []), "token_set"),
        ]

        ambiguous = False
        for cands, method in attempts:
            if not cands:
                continue
            hit = _unique_identity(cands)
            if hit:
                return hit, method
            narrowed = _context_filter(cands, party, constituency)
            hit = _unique_identity(narrowed)
            if hit:
                return hit, f"{method}+context"
            ambiguous = True

        return None, "ambiguous" if ambiguous else "unmatched"


def build_roster(persons: list[dict], reference: list[dict]) -> pa.Table:
    matcher = _Matcher(reference)
    rows: list[dict] = []
    for p in persons:
        hit, method = matcher.match(p["name"], p.get("party"), p.get("constituency"))
        rows.append(
            {
                "date": p["date"],
                "person_index": p["person_index"],
                "section_heading": p["section_heading"],
                "person_header": p["person_header"],
                "name": p["name"],
                "party": p["party"],
                "constituency": p["constituency"],
                "api_person_id": hit["api_person_id"] if hit else None,
                "etternavn": hit["etternavn"] if hit else None,
                "fornavn": hit["fornavn"] if hit else None,
                "foedselsdato": hit["foedselsdato"] if hit else None,
                "kjoenn": hit["kjoenn"] if hit else None,
                "match_method": method,
            }
        )
    return pa.Table.from_pylist(rows, schema=ROSTER_SCHEMA)


NAME_CHANGES_SCHEMA = pa.schema(
    [
        ("api_person_id", pa.string()),
        ("foedselsdato", pa.string()),
        ("printed_name", pa.string()),
        ("first_date", pa.string()),
        ("last_date", pa.string()),
        ("n_snapshots", pa.int32()),
        ("match_methods", pa.string()),
    ]
)


def build_name_changes(roster: pa.Table) -> pa.Table:
    by_id: dict[str, dict[str, dict]] = {}
    dob: dict[str, str] = {}
    for r in roster.to_pylist():
        pid = r["api_person_id"]
        if not pid:
            continue
        dob[pid] = r["foedselsdato"]
        slot = by_id.setdefault(pid, {}).setdefault(
            r["name"], {"first": r["date"], "last": r["date"], "n": 0, "methods": set()}
        )
        slot["first"] = min(slot["first"], r["date"])
        slot["last"] = max(slot["last"], r["date"])
        slot["n"] += 1
        slot["methods"].add(r["match_method"])
    rows = []
    for pid, names in by_id.items():
        if len(names) < 2:
            continue
        for name, s in sorted(names.items(), key=lambda kv: kv[1]["first"]):
            rows.append(
                {
                    "api_person_id": pid,
                    "foedselsdato": dob[pid],
                    "printed_name": name,
                    "first_date": s["first"],
                    "last_date": s["last"],
                    "n_snapshots": s["n"],
                    "match_methods": ",".join(sorted(s["methods"])),
                }
            )
    if not rows:
        return NAME_CHANGES_SCHEMA.empty_table()
    return pa.Table.from_pylist(rows, schema=NAME_CHANGES_SCHEMA)
