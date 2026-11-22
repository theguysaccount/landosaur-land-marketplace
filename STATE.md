# STATE

- Original: Next.js 16 + SQLite on one Fly machine (landosaur.fly.dev), private repo, daily crawler, accounts,
  worksheets, buying help. On 2026-11-22 it timed out on every path. Left untouched.
- Local copy (iCloud, copied to `original/`, never committed): full source except two crawler modules
  (`parcel-enrichment.ts`, `landcentral-detail.ts` are imported but missing), the 2026-10-02 public catalogue
  snapshot (9,745 records), USDA data, guides, brand assets.
- Built (2026-11-22): static edition with five official sources crawled daily in Python (10,288 listings on the
  first run: 7,452 St. Louis lots, 2,807 Arkansas parcels, 18 Wisconsin, 10 Alaska Trust, 1 Alaska DNR), parcel
  outlines from agency GIS, map, listing/state/county pages, new and closing-soon pages with feeds, CSV/JSON, cost
  worksheet, county land values from the US County Land Index.
- Works: 14 unit tests, build guard over ~10,400 pages, headless-Chrome end-to-end test (map, filters, listing,
  worksheet, indexing policy, phone width).
- Reused: the original's adapter rules, source list, brand (mascot, dino mark, colours), map base layers.
- Not done (keys): domain, parcel-report checkout, support link, analytics.
