from pathlib import Path

import pytest

from stortingsverv_parser.carve import _split_header, tables_for_document
from stortingsverv_parser.layout import parse_document

FIXTURE = Path(__file__).parent / "fixtures" / "pr-2026-06-30.pdf"


@pytest.fixture(scope="module")
def parsed():
    return parse_document(str(FIXTURE))


def test_person_counts(parsed):
    by_heading = {}
    for p in parsed.persons:
        by_heading[p.section_heading] = by_heading.get(p.section_heading, 0) + 1
    assert by_heading == {
        "Representanter": 169,
        "Regjeringsmedlemmer": 20,
        "Vararepresentanter": 72,
    }


def test_zero_remainder(parsed):
    assert parsed.remainder == []


def test_first_person_section(parsed):
    p = parsed.persons[0]
    assert p.header == "Abdi, Hashim (A, Østfold)"
    s = p.sections[0]
    assert s.marker == "§2"
    assert s.label == "Styreverv mv."
    assert s.text.startswith("Folkevalgt verv i Fredrikstad kommune")


def test_notes_captured(parsed):
    notes = {p.note for p in parsed.persons if p.note}
    assert "Har ingen registreringspliktige interesser" in notes
    assert "Ingen registrerte opplysninger" in notes


def test_transaction_table(parsed):
    p = next(p for p in parsed.persons if p.header.startswith("Borgli"))
    t = p.tables[0]
    assert t.header_cells == [
        "Dato",
        "Kjøp/Salg",
        "Selskapsnavn",
        "Ansvarsform",
        "Eierandel (%)",
        "Antall",
        "Verdi (NOK)",
    ]
    assert t.marker == "§9"
    assert t.rows[0][0] == "22.04.2026"
    assert all(len(r) == len(t.header_cells) for r in t.rows)


def test_reglement_captured(parsed):
    assert "§ 1." in parsed.preamble_text
    assert "Registreringspliktige forhold" in parsed.preamble_text


def test_split_header():
    assert _split_header("Abdi, Hashim (A, Østfold)") == ("Abdi, Hashim", "A", "Østfold")
    assert _split_header("Eide, Espen Barth (A)") == ("Eide, Espen Barth", "A", None)
    assert _split_header("No Parens Here") == ("No Parens Here", None, None)


def test_tables_for_document(parsed):
    tabs = tables_for_document("2026-06-30", "http://x", "hash", parsed)
    assert len(tabs["documents"]) == 1
    assert len(tabs["persons"]) == 261
    assert tabs["documents"][0]["n_remainder_lines"] == 0
    sections = tabs["sections"]
    assert all(s["block_hash"] for s in sections)
    tx = tabs["transactions"]
    assert tx and all("Dato" in t["cells_json"] for t in tx)
