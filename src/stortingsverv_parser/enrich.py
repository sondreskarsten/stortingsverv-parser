"""Item-level enrichment of section blocks via GitHub Models.

Deterministic parsing stops at the section grain (person x paragraph,
text verbatim). Splitting a block into individual registered items and
lifting organisation, role, remuneration, amounts, dates and countries out
of free text is a derived layer. It is produced by a language model,
versioned by prompt and model id, and memoised by block hash so repeated
runs only pay for blocks never seen before. The raw text is never
replaced; items sit alongside it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

PROMPT_VERSION = "v1"
DEFAULT_MODEL = "openai/gpt-4o-mini"
ENDPOINT = "https://models.github.ai/inference/chat/completions"

SYSTEM_PROMPT = """You extract structured items from blocks of the Norwegian parliamentary register of members' positions and economic interests (Stortingsrepresentantenes verv og økonomiske interesser). Each block is the full text a person registered under one paragraph (§) of the register regulation.

For every block, split the text into its distinct registered items (one verv, one company holding, one trip, one gift, one agreement, etc.). Return JSON only, of the form:
{"blocks": [{"id": <int>, "items": [{...}, ...]}, ...]}

Each item object has exactly these keys (use null when the text does not state a value):
- "item_text": the verbatim text of this item, copied character for character from the block, in the original language. Every content-bearing part of the block must be covered by exactly one item's item_text. Do not translate, do not paraphrase, do not fix spelling.
- "organisation": name of the company, organisation, public body or counterpart, as written.
- "role": the position, holding or relationship described (e.g. styremedlem, leder, aksjer, gårdbruker, permisjon), as written.
- "remuneration": the verbatim phrase describing compensation status if present (e.g. "godtgjørelse", "ikke lønnet", "møtegodtgjørelse").
- "amount_nok": integer NOK amount if an amount is explicitly stated, else null.
- "share_count": integer number of shares if explicitly stated, else null.
- "share_pct": ownership percentage as a number if explicitly stated, else null.
- "org_number": Norwegian organisation number (9 digits) if explicitly stated, else null.
- "date_from": ISO date (YYYY-MM-DD, or YYYY-MM or YYYY if only that precision is stated) for a start/event date, else null.
- "date_to": ISO date for an end date, else null.
- "country": country name if the item concerns travel or a foreign counterpart, else null.

Rules: an empty block returns an empty items list. If a block is one indivisible statement, return a single item. Never invent values not present in the text."""


def _shard_path(cache_dir: Path, h: str) -> Path:
    return cache_dir / PROMPT_VERSION / f"{h[:2]}.jsonl"


def load_cache(cache_dir: Path) -> dict[str, list[dict]]:
    cache: dict[str, list[dict]] = {}
    d = cache_dir / PROMPT_VERSION
    if not d.exists():
        return cache
    for f in sorted(d.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            cache[rec["block_hash"]] = rec["items"]
    return cache


def append_cache(cache_dir: Path, records: list[dict]) -> None:
    by_shard: dict[Path, list[dict]] = {}
    for rec in records:
        by_shard.setdefault(_shard_path(cache_dir, rec["block_hash"]), []).append(rec)
    for path, recs in by_shard.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _call_model(
    client: httpx.Client, token: str, model: str, batch: list[dict]
) -> dict[int, list[dict]]:
    user = "\n\n".join(
        f"BLOCK id={b['id']} paragraf={b['paragraf']} label={b['label']}\n{b['text']}"
        for b in batch
    )
    resp = client.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        },
        timeout=120,
    )
    if resp.status_code == 429:
        raise RateLimited(resp.headers.get("retry-after"))
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    out: dict[int, list[dict]] = {}
    for blk in parsed.get("blocks", []):
        out[int(blk["id"])] = blk.get("items", [])
    return out


class RateLimited(Exception):
    def __init__(self, retry_after: str | None):
        self.retry_after = retry_after
        super().__init__(f"rate limited, retry-after={retry_after}")


def enrich_blocks(
    blocks: list[dict],
    cache_dir: Path,
    token: str,
    model: str = DEFAULT_MODEL,
    max_requests: int = 120,
    batch_size: int = 6,
    min_interval_s: float = 4.5,
) -> dict:
    """blocks: [{block_hash, paragraf, label, text}]. Returns run stats.

    Only blocks absent from the cache are sent. Stops when max_requests is
    reached or a rate limit response signals the daily budget is exhausted;
    remaining blocks are picked up by the next run.
    """
    cache = load_cache(cache_dir)
    pending = [b for b in blocks if b["block_hash"] not in cache and b["text"].strip()]
    seen: set[str] = set()
    todo = []
    for b in pending:
        if b["block_hash"] in seen:
            continue
        seen.add(b["block_hash"])
        todo.append(b)

    for b in blocks:
        if b["block_hash"] not in cache and not b["text"].strip():
            cache[b["block_hash"]] = []
            append_cache(cache_dir, [{"block_hash": b["block_hash"], "items": [],
                                      "model": "none", "prompt_version": PROMPT_VERSION}])

    stats = {"cached": len(cache), "pending": len(todo), "requests": 0,
             "resolved": 0, "failed": 0, "stopped": None}
    if not todo or max_requests <= 0:
        return stats

    client = httpx.Client()
    last_call = 0.0
    for i in range(0, len(todo), batch_size):
        if stats["requests"] >= max_requests:
            stats["stopped"] = "max_requests"
            break
        batch = [
            {"id": j, **b} for j, b in enumerate(todo[i : i + batch_size])
        ]
        wait = min_interval_s - (time.monotonic() - last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            last_call = time.monotonic()
            result = _call_model(client, token, model, batch)
            stats["requests"] += 1
        except RateLimited as e:
            retry = float(e.retry_after) if e.retry_after else None
            if retry is not None and retry <= 90:
                time.sleep(retry + 1)
                try:
                    last_call = time.monotonic()
                    result = _call_model(client, token, model, batch)
                    stats["requests"] += 1
                except RateLimited:
                    stats["stopped"] = "rate_limited"
                    break
            else:
                stats["stopped"] = "rate_limited"
                break
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            stats["failed"] += len(batch)
            stats["requests"] += 1
            continue

        records = []
        for b in batch:
            items = result.get(b["id"])
            if items is None:
                stats["failed"] += 1
                continue
            records.append(
                {
                    "block_hash": b["block_hash"],
                    "items": items,
                    "model": model,
                    "prompt_version": PROMPT_VERSION,
                }
            )
            stats["resolved"] += 1
        append_cache(cache_dir, records)

    client.close()
    return stats
