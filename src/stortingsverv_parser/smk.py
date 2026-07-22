"""SMK register source: version manifest, wayback collector, tables, store.

The register lives at one rolling contentassets URL that Cloudflare
serves only to residential clients; the Internet Archive is the fetch
path. A version is a unique capture digest; its date is the cover's
"Dokument generert" line. The committed manifest pins every known
version (generated date, wayback timestamp, sha256); the collector asks
the CDX index for digests it has not seen, fetches them from the
archive, and appends. Tables: smk_documents (one row per version),
smk_persons (version x person), smk_fields (version x person x printed
field label, value verbatim).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .smk_layout import SMK_PARSER_VERSION, parse_smk

SOURCE_URL = (
    "https://www.regjeringen.no/contentassets/fc1a9092514341438119914b3e2b0461/"
    "register-for-verv-og-okonomiske-interesser.pdf"
)
CDX = (
    "https://web.archive.org/cdx/search/cdx?url=regjeringen.no%2Fcontentassets"
    "&matchType=prefix&filter=urlkey:.*register-for-verv.*&filter=statuscode:200"
    "&output=json&fl=timestamp,digest&limit=1000"
)
UA = {"User-Agent": "registrum-archive-audit/1.0 (+sondreskarsten@gmail.com)"}

SMK_TABLES = ["smk_documents", "smk_persons", "smk_fields"]

SMK_SCHEMAS = {
    "smk_documents": pa.schema(
        [
            ("generated", pa.string()),
            ("wayback_ts", pa.string()),
            ("source_url", pa.string()),
            ("wayback_url", pa.string()),
            ("file_hash", pa.string()),
            ("n_pages", pa.int32()),
            ("n_persons", pa.int32()),
            ("cover_text", pa.large_string()),
            ("n_remainder_lines", pa.int32()),
            ("remainder_json", pa.large_string()),
            ("parser_version", pa.string()),
        ]
    ),
    "smk_persons": pa.schema(
        [
            ("generated", pa.string()),
            ("person_index", pa.int32()),
            ("name", pa.string()),
            ("affiliation", pa.string()),
            ("parti", pa.string()),
            ("fylke", pa.string()),
            ("n_fields", pa.int32()),
        ]
    ),
    "smk_fields": pa.schema(
        [
            ("generated", pa.string()),
            ("person_index", pa.int32()),
            ("name", pa.string()),
            ("field_label", pa.string()),
            ("value", pa.large_string()),
            ("field_order", pa.int32()),
            ("is_header", pa.bool_()),
        ]
    ),
}


def _wayback_url(ts: str) -> str:
    return f"https://web.archive.org/web/{ts}id_/{SOURCE_URL}"


def read_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def collect(manifest_path: Path, pdf_dir: Path) -> list[dict]:
    manifest = read_manifest(manifest_path)
    known_digests = {e["digest"] for e in manifest}
    raw = urllib.request.urlopen(
        urllib.request.Request(CDX, headers=UA), timeout=90
    ).read()
    rows = json.loads(raw)[1:]
    seen: dict[str, str] = {}
    for ts, digest in rows:
        seen.setdefault(digest, ts)
    new = []
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for digest, ts in sorted(seen.items(), key=lambda kv: kv[1]):
        if digest in known_digests:
            continue
        data = urllib.request.urlopen(
            urllib.request.Request(_wayback_url(ts), headers=UA), timeout=180
        ).read()
        if data[:4] != b"%PDF":
            continue
        local = pdf_dir / f"smk_{ts}.pdf"
        local.write_bytes(data)
        parse = parse_smk(str(local))
        entry = {
            "generated": parse.generated or ts[:8],
            "wayback_ts": ts,
            "digest": digest,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
        manifest.append(entry)
        new.append(entry)
        time.sleep(1)
    manifest.sort(key=lambda e: (e["generated"], e["wayback_ts"]))
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return new


def save_page_now() -> int:
    req = urllib.request.Request(
        f"https://web.archive.org/save/{SOURCE_URL}", headers=UA
    )
    try:
        return urllib.request.urlopen(req, timeout=120).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def tables_for_version(entry: dict, parse) -> dict[str, list[dict]]:
    g = entry["generated"]
    docs = [
        {
            "generated": g,
            "wayback_ts": entry["wayback_ts"],
            "source_url": SOURCE_URL,
            "wayback_url": _wayback_url(entry["wayback_ts"]),
            "file_hash": entry["sha256"],
            "n_pages": parse.n_pages,
            "n_persons": len(parse.persons),
            "cover_text": parse.cover_text,
            "n_remainder_lines": len(parse.remainder),
            "remainder_json": json.dumps(parse.remainder, ensure_ascii=False),
            "parser_version": parse.parser_version,
        }
    ]
    persons, fields = [], []
    for p in parse.persons:
        persons.append(
            {
                "generated": g,
                "person_index": p.order,
                "name": p.name,
                "affiliation": p.affiliation,
                "parti": p.parti,
                "fylke": p.fylke,
                "n_fields": len(p.fields),
            }
        )
        for f in p.fields:
            fields.append(
                {
                    "generated": g,
                    "person_index": p.order,
                    "name": p.name,
                    "field_label": f.label,
                    "value": f.value,
                    "field_order": f.order,
                    "is_header": f.is_header,
                }
            )
    return {"smk_documents": docs, "smk_persons": persons, "smk_fields": fields}


def parse_missing(manifest_path: Path, pdf_dir: Path, store_dir: Path) -> list[str]:
    parsed = []
    for e in read_manifest(manifest_path):
        key = f"{e['generated']}_{e['wayback_ts']}"
        snap = store_dir / key
        meta_path = snap / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if (
                meta.get("file_hash") == e["sha256"]
                and meta.get("parser_version") == SMK_PARSER_VERSION
            ):
                continue
        local = pdf_dir / f"smk_{e['wayback_ts']}.pdf"
        if not local.exists():
            data = urllib.request.urlopen(
                urllib.request.Request(_wayback_url(e["wayback_ts"]), headers=UA),
                timeout=180,
            ).read()
            pdf_dir.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
        digest = hashlib.sha256(local.read_bytes()).hexdigest()
        if digest != e["sha256"]:
            raise ValueError(f"smk sha mismatch for {key}")
        parse = parse_smk(str(local))
        tabs = tables_for_version(e, parse)
        snap.mkdir(parents=True, exist_ok=True)
        for name in SMK_TABLES:
            table = (
                pa.Table.from_pylist(tabs[name], schema=SMK_SCHEMAS[name])
                if tabs[name]
                else SMK_SCHEMAS[name].empty_table()
            )
            pq.write_table(table, snap / f"{name}.parquet")
        meta_path.write_text(
            json.dumps(
                {
                    "generated": e["generated"],
                    "wayback_ts": e["wayback_ts"],
                    "file_hash": e["sha256"],
                    "parser_version": SMK_PARSER_VERSION,
                    "n_persons": len(parse.persons),
                    "n_remainder_lines": len(parse.remainder),
                }
            )
        )
        parsed.append(key)
    return parsed


def archive_versions(
    manifest_path: Path, pdf_dir: Path, repo: str, token: str
) -> dict:
    import httpx

    from .archive import _assets, _ensure_release, _existing_manifest, _upload

    with httpx.Client(timeout=120) as client:
        rid = _ensure_release(client, token, repo, "pdf-archive")
        assets = _assets(client, token, repo, rid)
        existing = _existing_manifest(client, repo, assets)
        by_sha = {e.get("sha256") for e in existing}
        uploaded = 0
        for e in read_manifest(manifest_path):
            if e["sha256"] in by_sha:
                continue
            name = f"smk-{e['generated']}.pdf"
            if name in assets:
                name = f"smk-{e['generated']}-{e['sha256'][:8]}.pdf"
            local = pdf_dir / f"smk_{e['wayback_ts']}.pdf"
            _upload(client, token, repo, rid, name, local, "application/pdf")
            existing.append(
                {
                    "asset": name,
                    "date": e["generated"],
                    "sha256": e["sha256"],
                    "source": "smk-wayback",
                    "wayback_ts": e["wayback_ts"],
                }
            )
            uploaded += 1
        if uploaded:
            tmp = pdf_dir / "archive_manifest.json"
            tmp.write_text(json.dumps(existing, indent=1, ensure_ascii=False))
            if "archive_manifest.json" in assets:
                client.delete(
                    f"https://api.github.com/repos/{repo}/releases/assets/"
                    f"{assets['archive_manifest.json']}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            _upload(
                client, token, repo, rid, "archive_manifest.json", tmp, "application/json"
            )
            tmp.unlink()
    return {"smk_uploaded": uploaded, "entries": len(existing)}
