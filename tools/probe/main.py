import datetime, json, os, sys, time
from google.cloud import storage
from probe_lib import Limiter, dated_candidates, head

PREFIX = os.environ.get("GCS_PREFIX", "raw/stortingsverv_probe")
BUCKET = os.environ.get("GCS_BUCKET", "sondre_brreg_data")
RATE = float(os.environ.get("RATE", "18"))

def main():
    client = storage.Client()
    bucket = client.bucket(BUCKET)
    urls = set()
    cur = datetime.date(2017, 10, 1)
    end = datetime.date.today()
    while cur <= end:
        urls.update(dated_candidates(cur.year, cur.month, cur.day, extended=True))
        cur += datetime.timedelta(days=1)
    urls = sorted(urls)
    ck_blob = bucket.blob(f"{PREFIX}/checkpoint.json")
    hits_blob = bucket.blob(f"{PREFIX}/hits.jsonl")
    start = 0
    hits = []
    if ck_blob.exists():
        start = json.loads(ck_blob.download_as_text())["index"]
    if hits_blob.exists():
        hits = [json.loads(l) for l in hits_blob.download_as_text().splitlines() if l.strip()]
    lim = Limiter(RATE)
    errors = 0
    for i in range(start, len(urls)):
        lim.wait()
        st = head(urls[i])
        if st == 200:
            hits.append({"url": urls[i], "found_at": time.strftime("%F %T")})
            hits_blob.upload_from_string("\n".join(json.dumps(h) for h in hits) + "\n")
            print("HIT", urls[i], flush=True)
        if st in (403, 429, 503):
            errors += 1
            lim.penalize()
            time.sleep(30)
            if errors >= 12:
                ck_blob.upload_from_string(json.dumps({"index": i, "aborted": "blocked"}))
                print("ABORT blocked", i, flush=True)
                sys.exit(1)
        elif st == 404:
            errors = 0
            lim.reward()
        if i % 5000 == 0:
            ck_blob.upload_from_string(json.dumps({"index": i, "total": len(urls), "hits": len(hits)}))
            print("progress", i, "/", len(urls), "rate", round(lim.rate, 1), flush=True)
    ck_blob.upload_from_string(json.dumps({"index": len(urls), "total": len(urls), "hits": len(hits), "done": True}))
    print("DONE", len(urls), "hits", len(hits), flush=True)

if __name__ == "__main__":
    main()
