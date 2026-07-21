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
) -> None:
    qa = datasets.build(store, out, cache)
    typer.echo(json.dumps({k: v for k, v in qa.items() if k != "snapshots"}))


if __name__ == "__main__":
    app()
