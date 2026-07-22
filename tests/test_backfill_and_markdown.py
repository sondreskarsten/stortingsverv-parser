import json
import re
from pathlib import Path

from stortingsverv_parser.markdown import _esc, _md_table

MANIFEST = Path(__file__).parent.parent / "backfill" / "manifest.json"


def test_backfill_manifest_integrity():
    entries = json.loads(MANIFEST.read_text())
    assert len(entries) == 53
    assert sum(e["dataset"] for e in entries) == 52
    dates = [e["date"] for e in entries if e["dataset"]]
    assert len(set(dates)) == len(dates)
    assert min(dates) == "2011-07-29"
    assert max(dates) == "2026-04-12"
    for e in entries:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"])
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"])
        assert e["origin"] in ("live-arkiv", "wayback")
        assert e["url"].startswith("https://")
        if not e["dataset"]:
            assert e["alternate_of"] == e["date"]


def test_md_escaping():
    assert _esc("a|b\nc") == "a\\|b<br>c"
    assert _esc(None) == ""
    table = _md_table(["h1", "h2"], [["x|y", "line1\nline2"]])
    lines = table.splitlines()
    assert lines[0] == "| h1 | h2 |"
    assert lines[1] == "|---|---|"
    assert lines[2] == "| x\\|y | line1<br>line2 |"


def test_roster_reference_and_match():
    from stortingsverv_parser.roster import build_roster, load_reference

    ref = load_reference(Path(__file__).parent.parent / "backfill" / "stortinget_api")
    assert len(ref) > 2500
    assert all(r["foedselsdato"] for r in ref)
    persons = [
        {"date": "2026-06-30", "person_index": 1, "section_heading": "Representanter",
         "person_header": "Abdi, Hashim (A, Østfold)", "name": "Abdi, Hashim",
         "party": "A", "constituency": "Østfold"},
        {"date": "2026-06-30", "person_index": 2, "section_heading": "Representanter",
         "person_header": "X, Y (A, Oslo)", "name": "Ingenmatch, Finnesikke",
         "party": "A", "constituency": "Oslo"},
    ]
    roster = build_roster(persons, ref).to_pylist()
    assert roster[0]["match_method"] == "exact" and roster[0]["foedselsdato"]
    assert roster[1]["match_method"] == "unmatched" and roster[1]["foedselsdato"] is None


def test_smk_manifest_and_parser():
    import json

    from stortingsverv_parser.smk import SMK_TABLES, read_manifest

    man = read_manifest(Path(__file__).parent.parent / "smk" / "manifest.json")
    assert len(man) >= 12
    assert all(e["sha256"] and e["wayback_ts"] and e["generated"] for e in man)
    dates = [e["generated"] for e in man]
    assert dates == sorted(dates)
    assert SMK_TABLES == ["smk_documents", "smk_persons", "smk_fields"]
