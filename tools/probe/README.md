# Filename permutation prober

Search tooling for the recoverability audit, not part of the pipeline.
Generates the corpus-derived filename grammar (see docs/provenance.md) over
every date and HEAD-probes stortinget.no at a polite, backoff-controlled
rate with an identifying User-Agent. Deployed ad hoc as a Cloud Run job for
long sweeps; hits and a resumable checkpoint land in GCS and any finds are
integrated through backfill/manifest.json. The dataset pipeline itself
remains GitHub-only.
