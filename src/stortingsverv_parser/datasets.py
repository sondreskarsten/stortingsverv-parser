"""Incremental snapshot store and combined dataset build.

Each publication is parsed once per (file_hash, parser_version) into an
immutable per-snapshot directory. The combined datasets are rebuilt from
the store on every run; rows are never mutated, a new snapshot only adds
rows at its own date.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import carve
from .enrich import PROMPT_VERSION, load_cache
from .layout import PARSER_VERSION, parse_document

TABLE_NAMES = ["documents", "persons", "sections", "transactions"]

ITEM_FIELDS = [
    ("item_text", str),
    ("organisation", str),
    ("role", str),
    ("remuneration", str),
    ("amount_nok", int),
    ("share_count", int),
    ("share_pct", float),
    ("org_number", str),
    ("date_from", str),
    ("date_to", str),
    ("country", str),
]

ITEMS_SCHEMA = pa.schema(
    [
        ("date", pa.string()),
        ("person_index", pa.int32()),
        ("person_header", pa.string()),
        ("section_heading", pa.string()),
        ("paragraf", pa.string()),
        ("label", pa.string()),
        ("item_index", pa.int32()),
        ("item_text", pa.large_string()),
        ("organisation", pa.string()),
        ("role", pa.string()),
        ("remuneration", pa.string()),
        ("amount_nok", pa.int64()),
        ("share_count", pa.int64()),
        ("share_pct", pa.float64()),
        ("org_number", pa.string()),
        ("date_from", pa.string()),
        ("date_to", pa.string()),
        ("country", pa.string()),
        ("block_hash", pa.string()),
        ("model", pa.string()),
        ("prompt_version", pa.string()),
    ]
)


def read_manifest(mirror_dir: Path) -> list[dict]:
    t = pq.read_table(mirror_dir / "manifest.parquet")
    rows = t.to_pylist()
    return sorted(
        (r for r in rows if r.get("status") == "success"), key=lambda r: str(r["date"])
    )


def parse_missing(mirror_dir: Path, store_dir: Path) -> list[str]:
    parsed: list[str] = []
    for row in read_manifest(mirror_dir):
        date = str(row["date"])
        snap_dir = store_dir / date
        meta_path = snap_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("file_hash") == row["file_hash"] and meta.get(
                "parser_version"
            ) == PARSER_VERSION:
                continue
        pdf_path = mirror_dir / "pdfs" / Path(str(row["pdf_path"])).name
        parse = parse_document(str(pdf_path))
        tables = carve.tables_for_document(date, str(row["url"]), str(row["file_hash"]), parse)
        snap_dir.mkdir(parents=True, exist_ok=True)
        for name in TABLE_NAMES:
            pq.write_table(carve.to_table(name, tables[name]), snap_dir / f"{name}.parquet")
        meta_path.write_text(
            json.dumps(
                {
                    "date": date,
                    "file_hash": row["file_hash"],
                    "parser_version": PARSER_VERSION,
                    "n_persons": len(parse.persons),
                    "n_remainder_lines": len(parse.remainder),
                    "population_count": row.get("population_count"),
                }
            )
        )
        parsed.append(date)
    return parsed


def _concat(store_dir: Path, name: str) -> pa.Table:
    parts = [
        pq.read_table(p) for p in sorted(store_dir.glob(f"*/{name}.parquet"))
    ]
    if not parts:
        return carve.SCHEMAS[name].empty_table()
    return pa.concat_tables(parts)


def _coerce(value, typ):
    if value is None:
        return None
    try:
        if typ is int:
            return int(float(str(value).replace(" ", "").replace(",", ".")))
        if typ is float:
            return float(str(value).replace(" ", "").replace(",", "."))
        s = str(value).strip()
        return s or None
    except (ValueError, TypeError):
        return None


def build_items(sections: pa.Table, cache_dir: Path) -> pa.Table:
    cache = load_cache(cache_dir)
    meta = _cache_meta(cache_dir)
    rows: list[dict] = []
    for sec in sections.to_pylist():
        items = cache.get(sec["block_hash"])
        if not items:
            continue
        m = meta.get(sec["block_hash"], {})
        for i, item in enumerate(items, start=1):
            row = {
                "date": sec["date"],
                "person_index": sec["person_index"],
                "person_header": sec["person_header"],
                "section_heading": sec["section_heading"],
                "paragraf": sec["paragraf"],
                "label": sec["label"],
                "item_index": i,
                "block_hash": sec["block_hash"],
                "model": m.get("model"),
                "prompt_version": m.get("prompt_version", PROMPT_VERSION),
            }
            for fname, typ in ITEM_FIELDS:
                row[fname] = _coerce(item.get(fname), typ)
            rows.append(row)
    if not rows:
        return ITEMS_SCHEMA.empty_table()
    return pa.Table.from_pylist(rows, schema=ITEMS_SCHEMA)


def _cache_meta(cache_dir: Path) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    d = cache_dir / PROMPT_VERSION
    if not d.exists():
        return meta
    for f in sorted(d.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            meta[rec["block_hash"]] = {
                "model": rec.get("model"),
                "prompt_version": rec.get("prompt_version"),
            }
    return meta


def _write_csv_gz(table: pa.Table, path: Path) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(table.column_names)
    for row in table.to_pylist():
        writer.writerow([row[c] for c in table.column_names])
    path.write_bytes(gzip.compress(buf.getvalue().encode("utf-8")))


def _write_jsonl_gz(table: pa.Table, path: Path) -> None:
    buf = io.BytesIO()
    with gzip.open(buf, "wt", encoding="utf-8") as f:
        for row in table.to_pylist():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    path.write_bytes(buf.getvalue())


def build(store_dir: Path, out_dir: Path, cache_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    combined: dict[str, pa.Table] = {n: _concat(store_dir, n) for n in TABLE_NAMES}
    combined["items"] = build_items(combined["sections"], cache_dir)

    for name, table in combined.items():
        pq.write_table(table, out_dir / f"{name}.parquet", compression="zstd")
        _write_csv_gz(table, out_dir / f"{name}.csv.gz")
        _write_jsonl_gz(table, out_dir / f"{name}.jsonl.gz")

    sections = combined["sections"].to_pylist()
    nonempty = [s for s in sections if s["text"].strip()]
    cache = load_cache(cache_dir)
    enriched_hashes = {s["block_hash"] for s in nonempty if s["block_hash"] in cache}
    per_date: dict[str, dict] = {}
    for meta_path in sorted(store_dir.glob("*/meta.json")):
        m = json.loads(meta_path.read_text())
        per_date[m["date"]] = {
            "n_persons": m["n_persons"],
            "population_count": m.get("population_count"),
            "n_remainder_lines": m["n_remainder_lines"],
        }
    qa = {
        "n_snapshots": len(per_date),
        "date_range": [min(per_date), max(per_date)] if per_date else None,
        "rows": {n: combined[n].num_rows for n in combined},
        "sections_nonempty": len(nonempty),
        "sections_enriched_unique_blocks": len(enriched_hashes),
        "enrichment_coverage": round(
            len([s for s in nonempty if s["block_hash"] in cache]) / len(nonempty), 4
        )
        if nonempty
        else None,
        "snapshots": per_date,
    }
    (out_dir / "qa_report.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False))
    return qa


def read_backfill(path: Path) -> list[dict]:
    return [e for e in json.loads(Path(path).read_text()) if e.get("dataset")]


def parse_backfill(manifest_path: Path, store_dir: Path, pdf_dir: Path | None = None) -> list[str]:
    import hashlib
    import urllib.request

    parsed: list[str] = []
    for e in read_backfill(manifest_path):
        date = e["date"]
        snap_dir = store_dir / date
        meta_path = snap_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("file_hash") == e["sha256"] and meta.get("parser_version") == PARSER_VERSION:
                continue
        local = (pdf_dir / f"pr-{date}.pdf") if pdf_dir else None
        if local is not None and local.exists():
            data = local.read_bytes()
        else:
            data = urllib.request.urlopen(e["url"], timeout=120).read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != e["sha256"]:
            raise ValueError(f"backfill sha mismatch for {date}: {digest}")
        tmp = store_dir / f".backfill-{date}.pdf"
        store_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        parse = parse_document(str(tmp))
        tmp.unlink()
        tables = carve.tables_for_document(date, e["url"], e["sha256"], parse)
        snap_dir.mkdir(parents=True, exist_ok=True)
        for name in TABLE_NAMES:
            pq.write_table(carve.to_table(name, tables[name]), snap_dir / f"{name}.parquet")
        meta_path.write_text(
            json.dumps(
                {
                    "date": date,
                    "file_hash": e["sha256"],
                    "parser_version": PARSER_VERSION,
                    "n_persons": len(parse.persons),
                    "n_remainder_lines": len(parse.remainder),
                    "population_count": None,
                    "origin": f"backfill-{e['origin']}",
                    "ajourfort": e.get("ajourfort"),
                }
            )
        )
        parsed.append(date)
    return parsed
