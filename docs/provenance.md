# Provenance: publication regimes of the register, 2009-2026

Everything below was established empirically in July 2026 by sweeping the
live site, the Internet Archive CDX index, and archived landing-page
snapshots, then probing candidate URLs against the live site. It is the
authoritative map of where register publications have lived, what survives,
and what is lost.

## Era map

| Era | Regime | URL | Survives |
|---|---|---|---|
| 2009 to ~2014 | One rolling PDF, overwritten in place; lived at two roots over time | `stortinget.no/Global/pdf/Diverse/verv og økonomiske interesser.pdf`, later `stortinget.no/Global/pdf/register for stortingsrepresentantenes og regjeringsmedlemmenes verv og okonomiske interesser.pdf` | Three Internet Archive captures: covers 2011-07-29, 2013-08-21, 2014-06-20 |
| ~2015 to 2017 | Rolling fixed-name PDFs, overwritten in place | `globalassets/pdf/verv_oekonomiske_interesser_register/register-for-stortingsrepresentantene-...pdf`, later `verv_ok_interesser.pdf` | Three captures: covers 2016-12-19, 2020-03-23 (alternate bytes of a dated file), 2020-06-26 (byte-identical to a dated file) |
| 2017-11 to 2022-10 | Dated PDFs, irregular filenames | `verv-og-okonomiske-interesser-register/{period}/pr…pdf`, folders with and without `arkiv_` | All 45 known publications still live under the current base (see below) |
| 2022-10 onward | Dated PDFs, normalized filenames | `verv-og-okonomiske-interesser/arkiv_{period}/pr-D-måned-YYYY.pdf` (base was `-register` until the 2026 site restructure) | Fully live; collected by the sibling repo |

## Filename irregularities, 2017-2022

The dated era used no consistent scheme. Observed forms, all live today:
`pr-20-november-2017.pdf`, `pr.-25-september-2018.pdf`,
`pr.-25.-oktober-2018.pdf`, `pr.-16-okt-2019.pdf`, `pr.-18.-des-2019.pdf`,
`pr.-1.-sept.-2021.pdf`. Variation axes: `pr-` vs `pr.-`, day with or
without a trailing dot, month full or abbreviated, abbreviation with or
without a trailing dot. The sibling collector generates only the
normalized form, which is why these publications sat outside its mirror;
`backfill/manifest.json` in this repo pins them instead.

## The 2026 restructure

The archive moved wholesale from
`globalassets/pdf/verv-og-okonomiske-interesser-register/` to
`globalassets/pdf/verv-og-okonomiske-interesser/`. Every historical dated
file was placed under an `arkiv_{period}/` folder with its original
filename spelling preserved. Normalized rewrites of irregular names 404;
the original spellings return 200.

## What was recovered

52 publications outside the sibling repo's mirror (which starts
2022-10-18 and generates only normalized filenames):

- 45 dated publications, 2017-11-20 to 2022-08-31, all fetched live.
- 3 mirror-era publications the collector's discovery missed, fetched
  live: 2023-08-02 (irregular `pr.-2.-aug.-2023.pdf`, proving irregular
  naming recurs after 2022) and 2026-04-12 (normalized name the
  gap-fill tier never probed), both found via the landing-page capture
  timeline, plus 2022-12-20 (irregular `pr.-20.-desember-2022.pdf`)
  found by variant-probing the only mirror-era months with zero
  publications. All other cadence gaps (2018-02, 2019-09, 2021-02,
  2021-05, 2021-10, 2022-09, 2025-10) stayed empty under a
  1,280-1,920-candidate variant space per month.
  41 were found via the Internet Archive CDX index; 4 more
  (2021-11-19, 2022-03-23, 2022-04-29, 2022-08-31) were never crawled by
  the Archive and were found by brute-forcing the filename variant space
  across every gap month.
- 4 publications recoverable only from Internet Archive captures of the
  rolling fixed-URL files: 2011-07-29, 2013-08-21, 2014-06-20 and
  2016-12-19. Their dates come from the cover "Ajourført pr." line, since
  the URLs carry no date. The 2013 and 2014 documents print a single
  "Representanter" heading covering everyone, unlike every other year.

One alternate observation is archived without entering the datasets: an
Internet Archive capture of `verv_ok_interesser.pdf` whose cover matches
the live dated 2020-03-23 publication but whose bytes differ (a separate
export of the same content). One filename/cover mismatch exists in the
source material itself: the file named `pr-20-desember-2017.pdf` states
"Ajourført pr. 19. desember 2017" on its cover; the manifest records both.

## Retention asymmetry

Every dated filename ever discovered resolves live on the current server:
51 of 51 attempts. Retention on the `globalassets` tree appears total; no
removal policy is in evidence there. The losses are confined to the
retired `/Global/pdf/` tree, killed wholesale in the ~2014 CMS migration,
and to rolling files that were overwritten in place. Two further
sub-regimes are evidenced by landing-page links but have no surviving
bytes anywhere: a dated file `verv og økonomiske int 2010 03.pdf` (March
2010, the earliest online publication found) and a dated-filename folder
`Global/pdf/Verv_Oekonomiske_interesser_register/` (e.g. `2013-2806.pdf`
for 28 June 2013) that the Internet Archive never crawled. Undiscovered
dated-era publications, if any exist, are therefore almost certainly
still live; the bottleneck is learning their filenames, not retention.

## What is lost

The rolling fixed-URL regimes overwrote in place, so every version between
Archive crawls is gone from the public web: the surviving points in the
2009-2017 window are exactly 2011-07-29, 2013-08-21, 2014-06-20 and
2016-12-19; everything between and around them is unverifiable online.
The February 2009 landing-page capture links no register file at all, so
online publication may not predate roughly 2010. Two archives were probed
without result or without access: arquivo.pt holds no captures of any
register URL, and Nasjonalbiblioteket's Nettarkivet returns 403 on its
replay and CDX endpoints (access is application-gated; it very likely
holds the missing versions and is the strongest remaining recovery
avenue, alongside asking Stortinget directly). archive.today rate-limited
the probe and remains unqueried. Recovering them would require asking Stortinget directly. Months
inside the dated era with no publication after exhaustive variant probing
(2018-02, 2019-09, 2021-02, 2021-05, 2021-10, 2022-09, and summer breaks)
are read as genuine publication gaps, with the caveat that a name outside
the probed variant space would be indistinguishable from a gap.

## Layout stability

The two-column layout parsed by this repo is unchanged since at least the
2011 document: every recovered publication, 2011 included, parses with
zero remainder lines under the same coordinate rules as the 2026 ones.

## Identity attachment (roster table)

Downstream joins use (name, foedselsdato). The `roster` table attaches
Stortinget API identity to every parsed person row: the reference pool is
the raw `representanter` responses (fast plus vara, all with
foedselsdato) for every parliamentary period 2001-2029 plus the current
`regjering` response, committed verbatim under
`backfill/stortinget_api/` (2,831 unique persons). Matching is by printed
name with three uniqueness-guarded methods (exact "Etternavn, Fornavn",
surname plus first given-name token, order-and-hyphen-insensitive token
set); ambiguous and unmatched rows are flagged, never guessed. Attachment
rate is 99.0% of 44,136 rows (Representanter 99.6%, Vararepresentanter
98.8%, Regjeringsmedlemmer 94.7%). The residual is 36 unique names,
dominated by ministers who never sat in parliament: the historical
`regjering` endpoint ignores its period parameter and returns only the
sitting government, so past external ministers have no API record in the
pool. The mirror-era population JSON cross-check in `qa_report.json`
remains null for backfill snapshots; the roster table supersedes it for
identity purposes.

Name-change linking is deliberately paused. Looser methods (surname-token
intersection, unique-given-name) recovered true surname changes but an
audit showed they also produce false links (a 1972-born minister mapped to
a 2003-born namesake via given-name uniqueness plus context). When
resumed, two safeguards are required before any link is admitted: the old
and the new printed name must never co-occur in the same snapshot, and
the person key must be anchored on foedselsdato, which is immutable and
near-unique in this space (two collisions in 2,831), rather than on
names. Until then the roster ships only the conservative methods.
