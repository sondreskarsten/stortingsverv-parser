"""Markdown table export of the latest snapshot, for browsing on GitHub.

Renders the newest publication as plain markdown tables committed to the
repo, so the current register is readable in the GitHub UI without
downloading release assets. Cell text stays verbatim except for the two
substitutions markdown tables force: pipes are escaped and newlines become
<br>.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from .enrich import load_cache


def _esc(value) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(_esc(v) for v in r) + " |")
    return "\n".join(out) + "\n"


def _latest_date(store_dir: Path) -> str:
    dates = sorted(p.parent.name for p in store_dir.glob("*/meta.json"))
    return dates[-1]


def export_markdown(store_dir: Path, out_dir: Path, cache_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    date = _latest_date(store_dir)
    snap = store_dir / date

    metas = [json.loads(p.read_text()) for p in sorted(store_dir.glob("*/meta.json"))]
    docs = {
        r["date"]: r
        for r in pq.read_table(
            snap / "documents.parquet", columns=["date", "url", "n_pages"]
        ).to_pylist()
    }
    doc_rows = []
    for m in reversed(metas):
        url_row = None
        d_dir = store_dir / m["date"] / "documents.parquet"
        url_row = pq.read_table(d_dir, columns=["url", "n_pages"]).to_pylist()[0]
        doc_rows.append(
            [
                f"[{m['date']}]({url_row['url']})",
                f"[pdf](../../../releases/download/pdf-archive/pr-{m['date']}.pdf)",
                url_row["n_pages"],
                m["n_persons"],
                m.get("population_count"),
                m["n_remainder_lines"],
            ]
        )
    (out_dir / "documents.md").write_text(
        "# Publications\n\nOne row per register publication, newest first. "
        "Date links to the source PDF on stortinget.no; archived links to the "
        "sha256-verified copy on the pdf-archive release, kept in case the "
        "source disappears. archive_manifest.json on that release resolves "
        "hash-exact assets, including any replaced versions.\n\n"
        + _md_table(
            ["date", "archived", "pages", "persons parsed", "population roster", "remainder lines"],
            doc_rows,
        )
    )

    persons = pq.read_table(snap / "persons.parquet").to_pylist()
    person_rows = [
        [
            p["person_index"],
            p["section_heading"],
            p["name"],
            p["party"],
            p["constituency"],
            p["note"],
            p["n_sections"],
            p["n_transaction_rows"],
        ]
        for p in persons
    ]
    (out_dir / "persons.md").write_text(
        f"# Persons, snapshot {date}\n\n"
        + _md_table(
            [
                "idx",
                "section",
                "name",
                "party",
                "constituency",
                "note",
                "sections",
                "tx rows",
            ],
            person_rows,
        )
    )

    sections = pq.read_table(snap / "sections.parquet").to_pylist()
    section_rows = [
        [s["person_index"], s["person_header"], s["paragraf"], s["label"], s["text"]]
        for s in sections
    ]
    (out_dir / "sections.md").write_text(
        f"# Registered interests, snapshot {date}\n\nText verbatim from the PDF text layer.\n\n"
        + _md_table(["idx", "person", "§", "label", "text"], section_rows)
    )

    tx = pq.read_table(snap / "transactions.parquet").to_pylist()
    tx_cols: list[str] = []
    parsed_tx = []
    for t in tx:
        cells = json.loads(t["cells_json"])
        for k in cells:
            if k not in tx_cols:
                tx_cols.append(k)
        parsed_tx.append((t, cells))
    tx_rows = [
        [t["person_header"], t["paragraf"]] + [cells.get(c) for c in tx_cols]
        for t, cells in parsed_tx
    ]
    (out_dir / "transactions.md").write_text(
        f"# Share transactions, snapshot {date}\n\nColumns are the printed table headers.\n\n"
        + _md_table(["person", "§"] + tx_cols, tx_rows)
    )

    cache = load_cache(cache_dir)
    item_rows = []
    covered = 0
    nonempty = [s for s in sections if s["text"].strip()]
    for s in nonempty:
        items = cache.get(s["block_hash"])
        if items is None:
            continue
        covered += 1
        for it in items:
            item_rows.append(
                [
                    s["person_header"],
                    s["paragraf"],
                    it.get("item_text"),
                    it.get("organisation"),
                    it.get("role"),
                    it.get("remuneration"),
                    it.get("amount_nok"),
                    it.get("share_pct"),
                    it.get("share_count"),
                    it.get("org_number"),
                    it.get("date_from"),
                    it.get("date_to"),
                    it.get("country"),
                ]
            )
    coverage = round(covered / len(nonempty), 4) if nonempty else None
    (out_dir / "items.md").write_text(
        f"# Items (model-derived), snapshot {date}\n\n"
        f"Derived layer: blocks split into items by a language model. "
        f"Coverage {covered}/{len(nonempty)} non-empty blocks ({coverage}). "
        "Uncovered blocks are absent here but present verbatim in sections.md.\n\n"
        + _md_table(
            [
                "person",
                "§",
                "item_text",
                "organisation",
                "role",
                "remuneration",
                "amount_nok",
                "share_pct",
                "share_count",
                "org_number",
                "from",
                "to",
                "country",
            ],
            item_rows,
        )
    )

    (out_dir / "README.md").write_text(
        f"# Latest snapshot as markdown\n\nSnapshot {date}. Regenerated by the "
        "parse-and-release workflow; do not edit by hand.\n\n"
        "- [documents.md](documents.md): all publications, newest first\n"
        "- [persons.md](persons.md): person roster of the latest publication\n"
        "- [sections.md](sections.md): every registered interest block, verbatim\n"
        "- [transactions.md](transactions.md): §9 share-transaction grids\n"
        "- [items.md](items.md): model-derived item split (partial coverage)\n\n"
        "Full history in all formats: the "
        "[data-latest release](../../../releases/tag/data-latest).\n"
    )
    return {"date": date, "files": 6, "sections": len(section_rows), "items": len(item_rows)}
