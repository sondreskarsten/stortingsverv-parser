import json
import re
from pathlib import Path

from stortingsverv_parser.markdown import _esc, _md_table

MANIFEST = Path(__file__).parent.parent / "backfill" / "manifest.json"


def test_backfill_manifest_integrity():
    entries = json.loads(MANIFEST.read_text())
    assert len(entries) == 48
    assert sum(e["dataset"] for e in entries) == 47
    dates = [e["date"] for e in entries if e["dataset"]]
    assert len(set(dates)) == len(dates)
    assert min(dates) == "2011-07-29"
    assert max(dates) == "2022-08-31"
    for e in entries:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"])
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"])
        assert e["origin"] in ("live-arkiv", "wayback")
        assert e["url"].startswith("https://")
        if not e["dataset"]:
            assert e["alternate_of"] == e["date"]
    assert all(e["date"] < "2022-10-18" for e in entries)


def test_md_escaping():
    assert _esc("a|b\nc") == "a\\|b<br>c"
    assert _esc(None) == ""
    table = _md_table(["h1", "h2"], [["x|y", "line1\nline2"]])
    lines = table.splitlines()
    assert lines[0] == "| h1 | h2 |"
    assert lines[1] == "|---|---|"
    assert lines[2] == "| x\\|y | line1<br>line2 |"
