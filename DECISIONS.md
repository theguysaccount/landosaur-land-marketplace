# DECISIONS

## 1. A static edition built on top of the live original
The original (Next.js + SQLite on one Fly machine) stays up and untouched. This edition reproduces its core public
value (find official land offerings, see source-dated evidence, estimate all-in costs) as a static site that runs
itself on GitHub Actions. No cutover: duplicate pages are `noindex`, new pages (new listings, closing soon, feeds)
are indexed. One variable (`LANDO_INDEX_DUPLICATES`) would change that if Jack retires the original.

## 2. Official government and auction sources only
The original also read LandCentral, a private seller's catalogue. Left out: the brief is official government and
auction listings, and portal data rights are the biggest risk in the original's own risk list. GSA RealEstateSales.gov
stays out because its robots.txt disallows crawling. California DGS and BLM notices are listed on /sources/ as not
yet carried over.

## 3. Crawlers rewritten in Python, same rules as the original
The original's TypeScript adapters depend on its server and database, and two of the modules they import were not in
the iCloud copy. The Python adapters keep the original's rules: only available vacant lots in St. Louis (joined with
the full inventory by parcel ID), Arkansas minimum bids as minimum bids, no previous-owner names, no photos, no
invented prices, withdrawal only after two complete reads, partial reads never withdraw. Parcel outlines come from
the same agency GIS services the original used.

## 4. The original's live site could not be used as a source
On 2026-11-22 landosaur.fly.dev did not answer (timeouts on every path, also by direct IP). The local copy had
everything needed (adapters to port, the public catalogue snapshot, brand assets), and fresh data comes from the
agencies directly, so nothing was recovered from the live site.

## 5. Map without accounts or keys
Leaflet 1.9.4 and Leaflet.markercluster 1.5.3, vendored from the npm registry with verified integrity. Base maps:
OpenStreetMap (attribution, light use) plus USGS The National Map topo and imagery (public domain).

## 6. "New" means new
A source's first read marks nothing as new (otherwise the first feed would claim 10,000 new listings). After that, a
listing is new on the day it first appears. Arkansas states when each parcel was added, so its dates are real from
day one.

## 7. Defaults chosen instead of asking
- Revenue ring first (open question): a parcel report, behind the `LANDO_REPORT_URL` key, because the evaluator's
  cheapest test is a report checkout on listing pages. Not live until Jack picks a checkout and fulfilment.
- "Buying help", broker matching and inbox: not in the static edition (licensing and RESPA risk; needs a backend).
- Launch states: whatever official sources are crawlable today (MO, AR, WI, AK); more via new adapters.
