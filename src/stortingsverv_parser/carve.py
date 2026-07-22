"""Assemble the locked table set from parsed documents.

Frame: the reglement printed in every publication (§§2-11, §15) carves the
registrable interests; the document's own layout carves persons into three
sections. Grain per table: documents (one row per publication), persons
(one row per person block), sections (one row per person x paragraph
block, text verbatim), transactions (one row per printed transaction-table
row, columns named by the table's own header cells).
"""

from __future__ import annotations

import hashlib
import json

import pyarrow as pa

from .layout import DocumentParse


def _split_header(header: str) -> tuple[str, str | None, str | None]:
    if "(" not in header or ")" not in header:
        return header.strip(), None, None
    name = header.split("(", 1)[0].strip().rstrip(",")
    inside = header.split("(", 1)[1].rsplit(")", 1)[0]
    if "," in inside:
        parts = [p.strip() for p in inside.split(",")]
        if len(parts) >= 3 and parts[0].isdigit():
            return name, parts[1], ", ".join(parts[2:])
        party, constituency = inside.split(",", 1)
        return name, party.strip(), constituency.strip()
    return name, inside.strip() or None, None


def block_hash(marker: str, label: str, text: str) -> str:
    return hashlib.sha256(f"{marker}\n{label}\n{text}".encode()).hexdigest()


def tables_for_document(
    date: str, url: str, file_hash: str, parse: DocumentParse
) -> dict[str, list[dict]]:
    documents = [
        {
            "date": date,
            "url": url,
            "file_hash": file_hash,
            "n_pages": parse.n_pages,
            "n_persons": len(parse.persons),
            "cover_text": parse.cover_text,
            "reglement_text": parse.preamble_text,
            "column_split": parse.column_split,
            "n_remainder_lines": len(parse.remainder),
            "remainder_json": json.dumps(parse.remainder, ensure_ascii=False),
            "parser_version": parse.parser_version,
        }
    ]

    persons: list[dict] = []
    sections: list[dict] = []
    transactions: list[dict] = []

    for p in parse.persons:
        name, party, constituency = _split_header(p.header)
        persons.append(
            {
                "date": date,
                "person_index": p.order,
                "section_heading": p.section_heading,
                "person_header": p.header,
                "name": name,
                "party": party,
                "constituency": constituency,
                "note": p.note or None,
                "n_sections": len(p.sections),
                "n_transaction_rows": sum(len(t.rows) for t in p.tables),
            }
        )
        for s in p.sections:
            sections.append(
                {
                    "date": date,
                    "person_index": p.order,
                    "person_header": p.header,
                    "section_heading": p.section_heading,
                    "paragraf": s.marker,
                    "label": s.label,
                    "text": s.text,
                    "n_lines": len(s.content_lines),
                    "section_order": s.order,
                    "block_hash": block_hash(s.marker, s.label, s.text),
                }
            )
        for t in p.tables:
            for i, row in enumerate(t.rows, start=1):
                transactions.append(
                    {
                        "date": date,
                        "person_index": p.order,
                        "person_header": p.header,
                        "paragraf": t.marker,
                        "row_index": i,
                        "cells_json": json.dumps(
                            dict(zip(t.header_cells, row)), ensure_ascii=False
                        ),
                    }
                )

    return {
        "documents": documents,
        "persons": persons,
        "sections": sections,
        "transactions": transactions,
    }


SCHEMAS = {
    "documents": pa.schema(
        [
            ("date", pa.string()),
            ("url", pa.string()),
            ("file_hash", pa.string()),
            ("n_pages", pa.int32()),
            ("n_persons", pa.int32()),
            ("cover_text", pa.large_string()),
            ("reglement_text", pa.large_string()),
            ("column_split", pa.float64()),
            ("n_remainder_lines", pa.int32()),
            ("remainder_json", pa.large_string()),
            ("parser_version", pa.string()),
        ]
    ),
    "persons": pa.schema(
        [
            ("date", pa.string()),
            ("person_index", pa.int32()),
            ("section_heading", pa.string()),
            ("person_header", pa.string()),
            ("name", pa.string()),
            ("party", pa.string()),
            ("constituency", pa.string()),
            ("note", pa.string()),
            ("n_sections", pa.int32()),
            ("n_transaction_rows", pa.int32()),
        ]
    ),
    "sections": pa.schema(
        [
            ("date", pa.string()),
            ("person_index", pa.int32()),
            ("person_header", pa.string()),
            ("section_heading", pa.string()),
            ("paragraf", pa.string()),
            ("label", pa.string()),
            ("text", pa.large_string()),
            ("n_lines", pa.int32()),
            ("section_order", pa.int32()),
            ("block_hash", pa.string()),
        ]
    ),
    "transactions": pa.schema(
        [
            ("date", pa.string()),
            ("person_index", pa.int32()),
            ("person_header", pa.string()),
            ("paragraf", pa.string()),
            ("row_index", pa.int32()),
            ("cells_json", pa.large_string()),
        ]
    ),
}


def to_table(name: str, rows: list[dict]) -> pa.Table:
    schema = SCHEMAS[name]
    if not rows:
        return schema.empty_table()
    return pa.Table.from_pylist(rows, schema=schema)
