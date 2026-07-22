from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from . import datasets
from .enrich import DEFAULT_MODEL, enrich_blocks

app = typer.Typer(add_completion=False, help="Parse the Stortinget register PDFs into datasets.")


@app.command()
def parse(
    mirror: Path = typer.Argument(..., help="Mirror dir produced by stortinget-register sync"),
    store: Path = typer.Argument(..., help="Per-snapshot parsed store"),
) -> None:
    parsed = datasets.parse_missing(mirror, store)
    typer.echo(f"parsed {len(parsed)} snapshots: {parsed}")


@app.command()
def enrich(
    store: Path = typer.Argument(...),
    cache: Path = typer.Argument(..., help="LLM cache directory (committed)"),
    max_requests: int = typer.Option(120),
    batch_size: int = typer.Option(6),
    model: str = typer.Option(DEFAULT_MODEL),
) -> None:
    token = os.environ.get("STV_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise typer.Exit(code=2)
    import pyarrow.parquet as pq

    seen: set[str] = set()
    blocks: list[dict] = []
    for p in sorted(store.glob("*/sections.parquet")):
        for row in pq.read_table(
            p, columns=["paragraf", "label", "text", "block_hash"]
        ).to_pylist():
            if row["block_hash"] in seen:
                continue
            seen.add(row["block_hash"])
            blocks.append(row)
    stats = enrich_blocks(
        blocks, cache, token, model=model, max_requests=max_requests, batch_size=batch_size
    )
    typer.echo(json.dumps(stats))


@app.command()
def backfill(
    manifest: Path = typer.Argument(...),
    store: Path = typer.Argument(...),
    pdf_dir: Path = typer.Option(None, "--pdf-dir"),
) -> None:
    parsed = datasets.parse_backfill(manifest, store, pdf_dir)
    typer.echo(f"backfilled {len(parsed)} snapshots: {parsed}")


@app.command(name="smk-collect")
def smk_collect(
    manifest: Path = typer.Argument(Path("smk/manifest.json")),
    pdf_dir: Path = typer.Option(Path("smk_pdfs"), "--pdf-dir"),
    spn: bool = typer.Option(True, "--spn/--no-spn"),
) -> None:
    from . import smk

    if spn:
        typer.echo(f"spn status: {smk.save_page_now()}")
    new = smk.collect(manifest, pdf_dir)
    typer.echo(f"new smk versions: {len(new)}: {[e['generated'] for e in new]}")


@app.command(name="smk-parse")
def smk_parse(
    manifest: Path = typer.Argument(Path("smk/manifest.json")),
    store: Path = typer.Argument(Path("store_smk")),
    pdf_dir: Path = typer.Option(Path("smk_pdfs"), "--pdf-dir"),
) -> None:
    from . import smk

    parsed = smk.parse_missing(manifest, pdf_dir, store)
    typer.echo(f"smk parsed {len(parsed)}: {parsed}")


@app.command(name="smk-archive")
def smk_archive(
    manifest: Path = typer.Argument(Path("smk/manifest.json")),
    pdf_dir: Path = typer.Option(Path("smk_pdfs"), "--pdf-dir"),
    repo: str = typer.Option(..., "--repo"),
) -> None:
    import os

    from . import smk

    token = os.environ["GITHUB_TOKEN"]
    typer.echo(json.dumps(smk.archive_versions(manifest, pdf_dir, repo, token)))


@app.command()
def archive(
    mirror: Path = typer.Argument(...),
    repo: str = typer.Option(..., "--repo"),
    tag: str = typer.Option("pdf-archive", "--tag"),
    backfill_manifest: Path = typer.Option(None, "--backfill"),
    pdf_dir: Path = typer.Option(None, "--pdf-dir"),
) -> None:
    token = os.environ.get("STV_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise typer.Exit(code=2)
    from .archive import archive_mirror

    stats = archive_mirror(mirror, repo, token, tag=tag,
                           backfill_manifest=backfill_manifest, pdf_dir=pdf_dir)
    typer.echo(json.dumps(stats))


@app.command(name="export-md")
def export_md(
    store: Path = typer.Argument(...),
    out: Path = typer.Argument(...),
    cache: Path = typer.Option(Path("cache/llm"), "--cache"),
) -> None:
    from .markdown import export_markdown

    stats = export_markdown(store, out, cache)
    typer.echo(json.dumps(stats))


@app.command()
def build(
    store: Path = typer.Argument(...),
    out: Path = typer.Argument(...),
    cache: Path = typer.Option(Path("cache/llm"), "--cache"),
    smk_store: Path = typer.Option(Path("store_smk"), "--smk-store"),
) -> None:
    qa = datasets.build(store, out, cache, smk_store_dir=smk_store)
    typer.echo(json.dumps({k: v for k, v in qa.items() if k != "snapshots"}))


if __name__ == "__main__":
    app()
