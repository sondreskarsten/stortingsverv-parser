"""Archive every mirrored source PDF to a dedicated GitHub release.

The datasets carry each publication's source url and sha256; this module
keeps the binaries themselves retrievable after stortinget.no removes or
replaces them. Assets are date-named; if a date's content ever changes, the
new observation is stored additionally under a hash-suffixed name, never
overwriting the first. archive_manifest.json on the same release maps every
(date, sha256) pair to its asset and records any hash mismatch between the
mirror manifest and the bytes on disk.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pyarrow.parquet as pq

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TAG = "pdf-archive"
MANIFEST_ASSET = "archive_manifest.json"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_release(client: httpx.Client, token: str, repo: str, tag: str) -> int:
    r = client.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=_headers(token))
    if r.status_code == 200:
        return r.json()["id"]
    r = client.post(
        f"{API}/repos/{repo}/releases",
        headers=_headers(token),
        json={
            "tag_name": tag,
            "name": "Source PDF archive",
            "body": "Every register publication PDF and population snapshot, "
            "sha256-verified, kept independently of stortinget.no availability. "
            "archive_manifest.json maps each (date, sha256) to its asset.",
        },
    )
    r.raise_for_status()
    return r.json()["id"]


def _assets(client: httpx.Client, token: str, repo: str, rid: int) -> dict[str, int]:
    out: dict[str, int] = {}
    page = 1
    while True:
        r = client.get(
            f"{API}/repos/{repo}/releases/{rid}/assets",
            headers=_headers(token),
            params={"per_page": 100, "page": page},
        )
        r.raise_for_status()
        batch = r.json()
        for a in batch:
            out[a["name"]] = a["id"]
        if len(batch) < 100:
            return out
        page += 1


def _upload(
    client: httpx.Client, token: str, repo: str, rid: int, name: str, path: Path, ctype: str
) -> None:
    r = client.post(
        f"{UPLOADS}/repos/{repo}/releases/{rid}/assets",
        headers={**_headers(token), "Content-Type": ctype},
        params={"name": name},
        content=path.read_bytes(),
        timeout=300,
    )
    r.raise_for_status()


def _existing_manifest(client: httpx.Client, repo: str, assets: dict[str, int]) -> list[dict]:
    if MANIFEST_ASSET not in assets:
        return []
    r = client.get(
        f"https://github.com/{repo}/releases/download/{TAG}/{MANIFEST_ASSET}",
        follow_redirects=True,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def archive_mirror(
    mirror_dir: Path,
    repo: str,
    token: str,
    tag: str = TAG,
    backfill_manifest: Path | None = None,
    pdf_dir: Path | None = None,
) -> dict:
    client = httpx.Client()
    rid = _ensure_release(client, token, repo, tag)
    assets = _assets(client, token, repo, rid)
    entries = _existing_manifest(client, repo, assets)
    known = {(e["date"], e["sha256"]) for e in entries}
    known_pop = {(e["date"], e.get("population_sha256")) for e in entries}

    rows = sorted(
        (
            r
            for r in pq.read_table(mirror_dir / "manifest.parquet").to_pylist()
            if r.get("status") == "success"
        ),
        key=lambda r: str(r["date"]),
    )

    stats = {"pdfs_uploaded": 0, "populations_uploaded": 0, "hash_mismatches": 0,
             "already_archived": 0}
    changed = False
    for row in rows:
        date = str(row["date"])
        pdf_path = mirror_dir / "pdfs" / Path(str(row["pdf_path"])).name
        local_sha = _sha256(pdf_path)
        mismatch = local_sha != row["file_hash"]
        if mismatch:
            stats["hash_mismatches"] += 1

        pop_name = None
        pop_sha = None
        if row.get("population_path"):
            pop_path = mirror_dir / "population" / Path(str(row["population_path"])).name
            if pop_path.exists():
                pop_sha = _sha256(pop_path)
                pop_name = f"population-{date}.json"
                if pop_name in assets and (date, pop_sha) not in known_pop:
                    pop_name = f"population-{date}-{pop_sha[:8]}.json"
                if pop_name not in assets:
                    _upload(client, token, repo, rid, pop_name, pop_path, "application/json")
                    assets[pop_name] = -1
                    stats["populations_uploaded"] += 1

        if (date, local_sha) in known:
            stats["already_archived"] += 1
            continue
        name = f"pr-{date}.pdf"
        if name in assets:
            name = f"pr-{date}-{local_sha[:8]}.pdf"
        if name not in assets:
            _upload(client, token, repo, rid, name, pdf_path, "application/pdf")
            assets[name] = -1
            stats["pdfs_uploaded"] += 1
        entries.append(
            {
                "date": date,
                "source_url": str(row["url"]),
                "sha256": local_sha,
                "mirror_manifest_sha256": row["file_hash"],
                "hash_mismatch": mismatch,
                "size_bytes": pdf_path.stat().st_size,
                "pdf_asset": name,
                "population_sha256": pop_sha,
                "population_asset": pop_name,
            }
        )
        known.add((date, local_sha))
        changed = True

    if backfill_manifest is not None and Path(backfill_manifest).exists():
        for e in json.loads(Path(backfill_manifest).read_text()):
            date = e["date"]
            sha = e["sha256"]
            if (date, sha) in known:
                stats["already_archived"] += 1
                continue
            local = (pdf_dir / f"pr-{date}.pdf") if pdf_dir else None
            if local is None or not local.exists():
                import urllib.request

                data = urllib.request.urlopen(e["url"], timeout=120).read()
                local = mirror_dir / f".bf-{date}.pdf"
                local.write_bytes(data)
            local_sha = _sha256(local)
            name = f"pr-{date}.pdf"
            if name in assets:
                name = f"pr-{date}-{local_sha[:8]}.pdf"
            if name not in assets:
                _upload(client, token, repo, rid, name, local, "application/pdf")
                assets[name] = -1
                stats["pdfs_uploaded"] += 1
            entries.append(
                {
                    "date": date,
                    "source_url": e["url"],
                    "sha256": local_sha,
                    "mirror_manifest_sha256": sha,
                    "hash_mismatch": local_sha != sha,
                    "size_bytes": local.stat().st_size,
                    "pdf_asset": name,
                    "population_sha256": None,
                    "population_asset": None,
                    "origin": f"backfill-{e['origin']}",
                    "ajourfort": e.get("ajourfort"),
                }
            )
            known.add((date, local_sha))
            changed = True

    if changed or MANIFEST_ASSET not in assets:
        if MANIFEST_ASSET in assets and assets[MANIFEST_ASSET] > 0:
            client.delete(
                f"{API}/repos/{repo}/releases/assets/{assets[MANIFEST_ASSET]}",
                headers=_headers(token),
            )
        tmp = mirror_dir / "archive_manifest.json"
        tmp.write_text(json.dumps(entries, indent=1, ensure_ascii=False))
        _upload(client, token, repo, rid, MANIFEST_ASSET, tmp, "application/json")
    client.close()
    stats["entries"] = len(entries)
    return stats
