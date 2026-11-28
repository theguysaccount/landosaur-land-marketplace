"""Build the static site into dist/ from data/.

    python3 -m lando.build [dist]

Generates:
  - Interactive Zillow-for-Land explorer (/), national directory (/land-for-sale/), state & county hubs
  - 50-State Land Price Observatory (/land-prices/* — 56 pages backed by USDA NASS 2010-2026 + 3,115 counties)
  - Research & Benchmarks (/research/) + source-cited buyer guides (/research/<slug>/)
  - Interactive Valuation, Financing & Off-Grid Power Workbench (/analyze/)
  - Individual GIS parcel dossiers (/land/<id>/)
  - CSV/JSON downloads, Atom feeds, Sitemap Index (/sitemap.xml -> /sitemaps/{core,places,listings}.xml),
    robots.txt, llms.txt, IndexNow key file, share cards, and manifest.json.
"""
from concurrent.futures import ProcessPoolExecutor
import base64
import csv
import gzip
import hashlib
import io
import json
import multiprocessing
import os
import statistics
import sys
import tarfile

from . import adapters, config, research
from .model import Catalog, STATE_NAMES
from .pages import DINO, Site, acres_text, esc, listing_is_indexable, price_line

STATIC = ["style.css", "theme.js", "geo.js", "watchlist.js", "share-chart.js", "map.js", "listing.js", "xray.js", "list.js", "direct.js", "services.js", "atlas.js", "tax_sales.js", "tables.js", "analyze.js", "favicon.svg", "mascot.png"]
ARCHIVED_PARCELS = "data/archived-parcels"


def agent_download(w):
    mcp_dir = os.path.join(config.ROOT, "mcp")
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name in ("package.json", "openapi.json", "landosaur-mcp.mjs"):
                with open(os.path.join(mcp_dir, name), "rb") as fh:
                    content = fh.read()
                member = tarfile.TarInfo("package/" + name)
                member.mode = 0o755 if name.endswith(".mjs") else 0o644
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
                if name == "openapi.json":
                    w.write("openapi.json", content)
    w.write("data/landosaur-mcp.tgz", out.getvalue())


class Writer(object):
    def __init__(self, dist):
        self.dist = dist
        self.pages = {}
        self.indexable = []
        self.indexable_groups = {"core": [], "places": [], "listings": []}
        self.files = 0
        self.outputs = set()
        self.directories = {dist}

    def write(self, rel, data, page_path=None, indexable=False, group="core"):
        full = os.path.join(self.dist, rel)
        directory = os.path.dirname(full)
        if directory not in self.directories:
            parent = os.path.dirname(directory)
            if parent in self.directories:
                try:
                    os.mkdir(directory)
                except FileExistsError:
                    if not os.path.isdir(directory):
                        raise
            else:
                os.makedirs(directory, exist_ok=True)
            self.directories.add(directory)
        if os.path.islink(full):
            os.unlink(full)
        raw = data.encode("utf-8") if isinstance(data, str) else data
        try:
            with open(full, "rb") as fh:
                unchanged = fh.read() == raw
        except FileNotFoundError:
            unchanged = False
        if not unchanged:
            with open(full, "wb") as fh:
                fh.write(raw)
        self.outputs.add(rel)
        self.files += 1
        if page_path is not None:
            self.pages[page_path] = hashlib.sha1(raw).hexdigest()[:16]
            if indexable:
                self.indexable.append(page_path)
                self.indexable_groups.setdefault(group, []).append(page_path)

    def page(self, path, html_, indexable=False, group="core"):
        rel = path.strip("/")
        self.write((rel + "/" if rel else "") + "index.html", html_, path, indexable and config.INDEXABLE, group=group)

    def prune(self):
        """Delete paths omitted by this build, including withdrawn listing directories."""
        for directory, children, files in os.walk(self.dist, topdown=False):
            for name in children:
                path = os.path.join(directory, name)
                if os.path.islink(path):
                    os.unlink(path)
            for name in files:
                full = os.path.join(directory, name)
                if full[len(self.dist) + 1:] not in self.outputs:
                    os.unlink(full)
            if directory != self.dist and directory not in self.directories and not os.listdir(directory):
                os.rmdir(directory)


def init_listing_worker(site):
    global _listing_site
    _listing_site = site


def write_listing_pages(writer, site, listings):
    archived = {}
    for row in listings:
        path, page = site.cat.listing_path(row), site.listing(row)
        if row["available"]:
            writer.page(path, page, indexable=listing_is_indexable(row), group="listings")
        else:
            raw = page.encode("utf-8")
            writer.pages[path] = hashlib.sha1(raw).hexdigest()[:16]
            archived[row["slug"]] = base64.b64encode(gzip.compress(raw, compresslevel=1, mtime=0)).decode("ascii")
    return archived


def write_listing_batch(bounds):
    dist, start, end = bounds
    writer = Writer(dist)
    archived = write_listing_pages(writer, _listing_site, _listing_site.cat.listings[start:end])
    return writer, archived


def write_listings(writer, site):
    listings = site.cat.listings
    if len(site.cat.by_id) != len(listings):
        raise ValueError("listing IDs must be unique across all official sources")
    workers = min(os.cpu_count() or 1, 4)
    if len(listings) < 5000 or workers < 2 or "fork" not in multiprocessing.get_all_start_methods():
        archived = write_listing_pages(writer, site, listings)
    else:
        # Build workers share the read-only snapshot and write disjoint parcel paths.
        os.makedirs(os.path.join(writer.dist, "land"), exist_ok=True)
        size = 350
        batches = [(writer.dist, start, min(start + size, len(listings))) for start in range(0, len(listings), size)]
        archived = {}
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork"),
                                 initializer=init_listing_worker, initargs=(site,)) as pool:
            for result, batch_archive in pool.map(write_listing_batch, batches):
                writer.pages.update(result.pages)
                writer.indexable.extend(result.indexable)
                writer.indexable_groups["listings"].extend(result.indexable)
                writer.outputs.update(result.outputs)
                writer.directories.update(result.directories)
                writer.files += result.files
                archived.update(batch_archive)

    buckets = {}
    for slug, content in archived.items():
        bucket = hashlib.sha256(slug.encode("ascii")).hexdigest()[:2]
        buckets.setdefault(bucket, {})[slug] = content
    for bucket, pages in buckets.items():
        writer.write("%s/%s.json" % (ARCHIVED_PARCELS, bucket), json.dumps(pages, separators=(",", ":")))


def atom(title, path, listings, cat, updated):
    entries = []
    for r in listings[:100]:
        url = config.BASE_URL + cat.listing_path(r)
        entries.append(
            "<entry><title>%s</title><link href=\"%s\"/><id>%s</id><updated>%sT00:00:00Z</updated>"
            "<summary>%s. %s; %s. Source: %s.</summary></entry>" % (
                esc(r["title"]), esc(url), esc(url), esc(r.get("first_seen") or updated), esc(r["status_label"]),
                esc(price_line(r)), esc(acres_text(r["acres"]).lower()), esc(cat.sources[r["source"]]["agency"])))
    return ('<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>%s</title>'
            '<link href="%s"/><link rel="self" href="%s"/><id>%s</id><updated>%sT00:00:00Z</updated>'
            '<author><name>Landosaur</name></author>%s</feed>') % (
        esc(title), esc(config.BASE_URL + "/new/"), esc(config.BASE_URL + path), esc(config.BASE_URL + path), esc(updated), "".join(entries))


def og_card(title, big, sub):
    return ('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:1200px;height:630px;overflow:hidden}'
            'body{background:#f6f8f2;color:#173628;font-family:"Arial Rounded MT Bold",system-ui,-apple-system,"Segoe UI",Roboto,"DejaVu Sans",sans-serif;'
            'display:flex;flex-direction:column;justify-content:space-between;padding:60px 70px;box-sizing:border-box;'
            'background-image:radial-gradient(circle at 90%% 20%%,#e3f6bb 0,#e3f6bb 220px,transparent 221px)}'
            '.b{display:flex;align-items:center;gap:18px;font-size:34px;font-weight:700;color:#1f6840}.b svg{width:72px;height:72px}'
            'h1{font-size:58px;line-height:1.06;margin:0;max-width:920px;letter-spacing:-.015em}.v{font-size:38px;color:#1f6840;font-weight:700}'
            '.s{font-size:25px;color:#5a6a5e}</style></head><body><div class="b">%s Landosaur</div><div><h1>%s</h1><p class="v">%s</p></div>'
            '<p class="s">%s</p></body></html>') % (DINO, esc(title), esc(big), esc(sub))


def write_share_templates(writer, cat, updated, new, cur):
    writer.write("_og/default.html", og_card(
        "Find, map, and value official land for sale",
        "%s listings · 50-state land prices" % "{:,}".format(len(cur)),
        "Official agencies, GIS flood & aerial maps, valuation workbench. Not an offer to sell."))
    writer.write("_og/research.html", og_card(
        "U.S. Public-Agency Land Benchmarks & Buyer Guides",
        "%s active official offerings" % "{:,}".format(len(cur)),
        "Computed directly from official public agency inventories. Zero invented prices."))
    writer.write("_og/new.html", og_card(
        "New government land listings",
        "%s in the last %d days" % ("{:,}".format(len(new)), config.NEW_DAYS),
        "Refreshed from official sources. Atom feeds by state."))
    writer.write("_og/closing.html", og_card(
        "Land auctions closing soon",
        "%s deadlines in the next %d days" % ("{:,}".format(len(cat.closing())), config.CLOSING_DAYS),
        "Official sources. Confirm cutoffs with the agency."))
    for st in cat.states.values():
        n = sum(1 for r in st["listings"] if r["available"])
        writer.write("_og/state-%s.html" % st["code"].lower(), og_card(
            "Government and auction land in %s" % st["name"],
            "%s current listings" % "{:,}".format(n),
            "Every listing links directly to the agency's own page."))



def build_llms_txt(cat, site, updated):
    cur = cat.current()
    b = research.compute_benchmarks(cat)
    states = sorted(cat.states.values(), key=lambda s: s["name"])
    base = config.BASE_URL
    lines = [
        "# Landosaur — Official U.S. Land Map, 50-State Land Price Observatory & Valuation Workbench",
        "",
        "Last reviewed: 2026-11-27",
        "",
        ("> Landosaur maps official public-agency land offerings across U.S. states and counties "
         "(tax-sale auctions, surplus state trust land, municipal land banks, and state redevelopment notices), "
         "paired with a 50-state USDA/FHFA Land Price Observatory (2010-%d across 3,115 counties), "
         "%d source-cited buyer research guides, and a deterministic land deal & off-grid power analyzer." % (
             site.market.latest_year, len(site.guides))),
        "",
        "## Platform Comparison (Landosaur vs. LandWatch, LandSearch, Land.com & Zillow Land)",
        "",
        "Published on the homepage (%s/#land-platform-comparison):" % base,
        "- **Inventory & source transparency**: Landosaur tracks %s active official public-agency offerings from %d agencies across %d states plus free direct owner/agent listings, linking every public parcel straight to its official agency portal; LandWatch, LandSearch, Land.com, and Zillow Land primarily index broker/MLS/seller classifieds routed through broker lead forms." % (
            "{:,}".format(len(cur)), b["agency_count"], b["state_count"]),
        "- **Due-diligence & GIS visibility**: Landosaur includes a free Parcel X-Ray (%s/xray/) covering USGS 3DEP LiDAR elevation/slope, FEMA NFHL flood & National Risk Index hazards, USFWS wetlands, USDA SSURGO soil/bedrock depth, Census roads, USGS PAD-US public lands, NASA solar and USDA hardiness, EIA electric utilities, and 3,115-county USDA/FHFA benchmarks; commercial listing portals leave federal GIS hazard and soil screening to external research." % base,
        "- **Deal modes, fees & open data**: Landosaur separates Buy It Now, Auction / Min Bid, Land Bank / Offer, and Direct listings, keeps search, listing, X-Ray, valuation modeling, CSV/JSON exports, and `/api/search/` free, and offers an optional turnkey Land Agent Concierge ($20 initiation + 10%% fee only on closed acquisitions) at %s/services/." % base,
        "",
        "## Key Platform Capabilities",
        "",
        "- **Live Official Inventory Map** (%s/): %s active official offerings across %d tracked states and %d agencies, with split-screen map/list filtering, saved shortlists, 4-parcel side-by-side comparison, GIS outlines, USGS aerial/topo tiles, FEMA NFHL flood hazard overlays, and a distance ruler." % (
            base, "{:,}".format(len(cur)), b["state_count"], b["agency_count"]),
        "- **50-State Land Price Observatory** (%s/land-prices/): Official USDA NASS 2010-%d farm real estate, cropland, and pasture series plus 3,115 county-level benchmarks across all 50 states." % (
            base, site.market.latest_year),
        "- **Interactive Land Analyzer** (%s/analyze/): Client-side all-in acquisition, land loan & balloon amortization, utility power extension vs. off-grid solar comparison, verified closed-comp envelope, 6-gate diligence check, income cap-rate, and subdivision residual calculator." % base,
        "- **Research & %d Due-Diligence Guides** (%s/research/): Deterministic public-agency price/acreage benchmarks plus source-cited field guides (tax sales, wetlands, septic, wells, road access, zoning, surveys, mineral rights, financing)." % (
            len(site.guides), base),
        "",
        "## Official Agency Sources (%s snapshot)" % updated,
        "",
    ]
    for src in adapters.SOURCES:
        count = cat.active_by_source.get(src["id"], 0)
        lines.append("- **%s** (%s) — %s (%s active %s)" % (
            src["agency"], STATE_NAMES.get(src["state"], src["state"]), src["about"],
            "{:,}".format(count), "listing" if count == 1 else "listings"))
    lines.extend([
        "",
        "## Primary Hub URLs",
        "",
        "- [Interactive Land Map](%s/)" % base,
        "- [Land Agent & Buyer Services ($20 Initiation + 10%% Transfer — Listed & Unlisted Land)](%s/services/)" % base,
        "- [U.S. Land Data Atlas & Interactive 50-State Charts](%s/land-atlas/)" % base,
        "- [Free U.S. Parcel X-Ray (All 50 States — Federal GIS and Electric Utility Data)](%s/xray/)" % base,
        "- [List Land Free (Owners, Real Estate Agents & AI Agents)](%s/list/)" % base,
        "- [Direct by Owner & Agent Marketplace (Live Auctions & Buy It Now)](%s/direct/)" % base,
        "- [Agent API Discovery](%s/.well-known/landosaur-agent.json)" % base,
        "- [OpenAPI 3.1 Specification](%s/openapi.json)" % base,
        "- [Landosaur MCP Server (stdio npm package)](%s/data/landosaur-mcp.tgz)" % base,
        "- [Land Under $5,000](%s/land-under-5000/)" % base,
        "- [Land Under $10,000](%s/land-under-10000/)" % base,
        "- [Acreage for Sale](%s/acreage-for-sale/)" % base,
        "- [Land for Sale by State (50-State Directory)](%s/land-for-sale/)" % base,
        "- [50-State Land Price Observatory](%s/land-prices/)" % base,
        "- [50-State Land Price Rankings](%s/land-prices/states/)" % base,
        "- [Cheapest Official Land Per Acre](%s/land-prices/cheapest-land-per-acre/)" % base,
        "- [U.S. Land Price History (2010-%d)](%s/land-prices/history/)" % (site.market.latest_year, base),
        "- [Land Deal, Electricity & Valuation Analyzer](%s/analyze/)" % base,
        "- [US Public-Agency Benchmarks & Buyer Guides](%s/research/)" % base,
        "- [Closing Soon Auctions & Proposals](%s/closing-soon/)" % base,
        "- [New Listings](%s/new/)" % base,
        "- [Official Sources & Read Health](%s/sources/)" % base,
        "- [Open Data Downloads (CSV & JSON)](%s/data/)" % base,
        "- [About & Disclosures](%s/about/)" % base,
        "",
        "## Tracked State Hubs",
        "",
    ])
    for st in states:
        avail = sum(1 for r in st["listings"] if r["available"])
        lines.append("- [%s](%s%s): %s active offerings (Atom feed: %s/feeds/%s.xml)" % (
            st["name"], base, cat.state_path(st), "{:,}".format(avail), base, st["code"].lower()))
    lines.extend(["", "## State Land Buying and Tax Sales", ""])
    lines.extend("- [%s](%s%s)" % (guide["title"], base, guide["path"])
                 for guide in site.guides if guide.get("state"))
    lines.extend([
        "",
        "## Machine-Readable Data & Discovery",
        "",
        "- [Listings CSV](%s/data/listings.csv)" % base,
        "- [Map JSON](%s/data/map.json)" % base,
        "- [Sources Status JSON](%s/data/sources.json)" % base,
        "- [50-State Land Data Atlas JSON (USDA 2010-2026 + 3,115 Counties + Supply)](%s/data/atlas.json)" % base,
        "- [Live Two-Sided Land Search API (JSON)](%s/api/search/?limit=25)" % base,
        "- [Land Agent Concierge API ($20 + 10%% Acquisition & Transfer)](%s/api/concierge/)" % base,
        "- [Buy It Now Atom Feed](%s/feeds/buy-now.xml)" % base,
        "- [Auctions Atom Feed](%s/feeds/auctions.xml)" % base,
        "- [New Listings Atom Feed](%s/feeds/new.xml)" % base,
    ])
    if config.INDEXABLE:
        lines.append("- [Sitemap Index](%s/sitemap.xml)" % base)
    lines.append("- [Robots Policy](%s/robots.txt)" % base)
    lines.append("")
    return "\n".join(lines)


def _urlset_xml(paths, updated):
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in sorted(set(paths)):
        out.append("<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (esc(config.BASE_URL + p), updated))
    out.append("</urlset>")
    return "\n".join(out) + "\n"


CENSUS_REGIONS = {
    "Northeast": "CT ME MA NH RI VT NJ NY PA".split(),
    "Midwest": "IN IL MI OH WI IA KS MN MO NE ND SD".split(),
    "South": "DE FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX".split(),
    "West": "AZ CO ID MT NV NM UT WY AK CA HI OR WA".split(),
}


def atlas_regions(states, series):
    by_code = {state["code"]: state for state in states}
    regions = []
    for name, codes in CENSUS_REGIONS.items():
        pairs = []
        for code in codes:
            history = series.get(code, {}).get("farm_real_estate")
            if history and len(history) >= 6 and history[-1] and history[-6]:
                pairs.append((history[-6], history[-1]))
        first = statistics.mean(p[0] for p in pairs) if pairs else None
        latest = statistics.mean(p[1] for p in pairs) if pairs else None
        regions.append({
            "name": name, "farm_real_estate": round(latest, 2) if latest else None,
            "five_year_cagr_pct": round(((latest / first) ** (1 / 5) - 1) * 100, 2) if first else None,
            "reporting_states": len(pairs), "total_states": len(codes),
            "active": sum(by_code[code]["active"] for code in codes if code in by_code),
        })
    return regions


def _build_atlas_payload(cat, site):
    m = site.market
    cur = cat.current()
    years = list(range(m.first_year, m.latest_year + 1))

    buy_now = sum(1 for r in cur if r["price_kind"] == "cash")
    auction = sum(1 for r in cur if r["price_kind"] == "min_bid" or r["status"] in ("auction_open", "auction_terms"))
    offer = len(cur) - buy_now - auction

    tiers_def = [
        ("< 0.25 ac (infill lot)", 0.0, 0.25),
        ("0.25 – 1 ac", 0.25, 1.0),
        ("1 – 5 ac", 1.0, 5.0),
        ("5 – 20 ac", 5.0, 20.0),
        ("20 – 100 ac", 20.0, 100.0),
        ("100+ ac", 100.0, 1e9),
    ]
    acre_tiers = []
    for lbl, lo, hi in tiers_def:
        cnt = sum(1 for r in cur if r.get("acres") and lo <= r["acres"] < hi)
        acre_tiers.append({"label": lbl, "count": cnt})

    def five_yr_chg(code):
        pts = [o for o in m.series(code, "farm_real_estate") if o.get("valueUsdPerAcre") is not None]
        target_yr = m.latest_year - 5
        p0 = next((o for o in pts if o["year"] == target_yr), None)
        p1 = next((o for o in reversed(pts) if o["year"] == m.latest_year), None)
        if not p0 or not p1 or not p0["valueUsdPerAcre"]:
            return None
        return round((p1["valueUsdPerAcre"] / float(p0["valueUsdPerAcre"]) - 1.0) * 100.0, 1)

    series = {}
    for code in ["US"] + sorted(STATE_NAMES.keys()):
        st_ser = {}
        has_any = False
        for metric in ("farm_real_estate", "cropland", "pasture"):
            by_y = {o["year"]: o.get("valueUsdPerAcre") for o in m.series(code, metric)}
            arr = [by_y.get(y) for y in years]
            if any(v is not None for v in arr):
                has_any = True
            st_ser[metric] = arr
        if has_any:
            series[code] = st_ser

    states_out = []
    priced_states = []
    for st in site.all_states:
        code = st["code"]
        chg_all, _, _ = m.span_change(code, "farm_real_estate")
        states_out.append({
            "code": code,
            "name": st["name"],
            "slug": st["slug"],
            "fre": st["values"].get("farm_real_estate"),
            "chg_all": chg_all,
            "chg_5yr": five_yr_chg(code),
            "county_median": st["county_median"],
            "active": st["active_count"],
            "browse_path": st["browse_path"] or st["path"],
            "price_path": st["path"],
        })
        st_rows = [r for r in cur if r["state"] == code and r.get("price") is not None and r["price"] > 0]
        if st_rows:
            ppas = [r["price"] / r["acres"] for r in st_rows if r.get("acres") and r["acres"] > 0]
            priced_states.append({
                "code": code,
                "name": st["name"],
                "priced_count": len(st_rows),
                "min_price": round(min(r["price"] for r in st_rows), 2),
                "median_ppa": round(statistics.median(ppas), 2) if ppas else None,
                "usda_fre": st["values"].get("farm_real_estate"),
                "browse_path": st["browse_path"] or st["path"],
            })
    priced_states.sort(key=lambda x: -x["priced_count"])

    counties = []
    for st in site.all_states:
        for c in m.counties_by_state.get(st["code"], []):
            counties.append([c["fips"], c["name"], st["code"], st["slug"], c["value"]])

    inflation_path = os.path.join(cat.data_dir, "market", "cpi-u.json")
    inflation = None
    if os.path.exists(inflation_path):
        with open(inflation_path, encoding="utf-8") as fh:
            inflation = json.load(fh)

    return {
        "inflation": inflation,
        "regions": atlas_regions(states_out, series),
        "first_year": m.first_year,
        "latest_year": m.latest_year,
        "years": years,
        "supply": {
            "total_active": len(cur),
            "buy_now": buy_now,
            "auction": auction,
            "offer": offer,
            "states_covered": len({r["state"] for r in cur}),
            "agencies_covered": len({cat.sources[r["source"]]["agency"] for r in cur}),
            "acre_tiers": acre_tiers,
        },
        "states": states_out,
        "series": series,
        "priced_states": priced_states,
        "counties": counties,
    }


def build(dist, data_dir=None, now=None, log=print):
    dist = os.path.abspath(dist)
    cat = Catalog(data_dir, now)
    site = Site(cat)
    os.makedirs(dist, exist_ok=True)
    w = Writer(dist)
    for name in STATIC:
        with open(os.path.join(config.SITE_SRC, name), "rb") as fh:
            w.write("assets/" + name, fh.read())
    vendor = os.path.join(config.SITE_SRC, "vendor")
    for directory, _, files in os.walk(vendor):
        for name in files:
            full = os.path.join(directory, name)
            with open(full, "rb") as fh:
                w.write("assets/vendor/" + os.path.relpath(full, vendor), fh.read())
    with open(os.path.join(config.SITE_SRC, "indexnow-key.txt")) as fh:
        key = fh.read().strip()
    w.write("%s.txt" % key, key)

    # Core hubs
    w.page("/", site.home(), indexable=True, group="core")
    w.page("/services/", site.services_page(), indexable=True, group="core")
    for ceiling in (5000, 10000):
        w.page("/land-under-%d/" % ceiling, site.budget_land_page(ceiling), indexable=True, group="core")
    w.page("/acreage-for-sale/", site.acreage_land_page(), indexable=True, group="core")
    w.page("/deals/", site.deals_page(), indexable=True, group="core")
    w.page("/tax-sales/", site.tax_sales_page(), indexable=True, group="core")
    w.page("/land-atlas/", site.land_atlas_page(), indexable=True, group="core")
    w.page("/xray/", site.xray_page(), indexable=True, group="core")
    w.page("/list/", site.list_page(), indexable=True, group="core")
    w.page("/direct/", site.direct_page(), indexable=True, group="core")
    w.page("/land-for-sale/", site.land_for_sale_index(), indexable=True, group="core")
    agent_download(w)
    agent_spec_path = os.path.join(config.SITE_SRC, "agent-api.json")
    if os.path.exists(agent_spec_path):
        with open(agent_spec_path, encoding="utf-8") as fh:
            spec_text = fh.read()
        w.write(".well-known/landosaur-agent.json", spec_text)
        w.write("agent-api.json", spec_text)
    w.page("/analyze/", site.analyze_page(), indexable=True, group="core")
    w.page("/research/", site.research(), indexable=True, group="core")
    w.page("/new/", site.new(), indexable=True, group="core")
    w.page("/closing-soon/", site.closing(), indexable=True, group="core")
    w.page("/sources/", site.sources_page(), indexable=True, group="core")
    w.page("/about/", site.about(), indexable=True, group="core")
    w.write("404.html", site.not_found())

    # 50-State Land Price Observatory (56 pages)
    w.page("/land-prices/", site.land_prices_index(), indexable=True, group="core")
    w.page("/land-prices/states/", site.land_prices_states(), indexable=True, group="core")
    w.page("/land-prices/cheapest-land-per-acre/", site.land_prices_cheapest(), indexable=True, group="core")
    w.page("/land-prices/history/", site.land_prices_history(), indexable=True, group="core")
    w.page("/land-prices/by-acreage/", site.land_prices_by_acreage(), indexable=True, group="core")
    w.page("/land-prices/data-methodology/", site.land_prices_methodology(), indexable=True, group="core")
    for st in site.all_states:
        w.page(st["path"], site.land_prices_state(st), indexable=True, group="core")

    # 29 Research Buyer Guides
    for g in site.guides:
        w.page(g["path"], site.guide_page(g), indexable=True, group="core")

    # Tracked state & county inventory hubs
    for st in cat.states.values():
        w.page(cat.state_path(st), site.state(st), indexable=True, group="places")
        for c in st["counties"].values():
            w.page(cat.county_path(st, c), site.county(st, c), indexable=True, group="places")
            for g in c["groups"]:
                w.page(cat.county_path(st, c) + g["slug"] + "/", site.county(st, c, g), indexable=False)

    # Individual listing dossiers (priced/deadline-bearing listings indexed in listings child sitemap)
    write_listings(w, site)

    # Map JSON & CSV downloads (includes deterministic % vs. USDA/FHFA county benchmark at col 14)
    state_fre = {
        code: (site.market.latest_values(code) or {}).get("farm_real_estate")
        for code in STATE_NAMES
    }
    rows = []
    for r in cat.listings:
        vs_pct = None
        if r.get("price") and r.get("acres") and r["price"] > 0 and r["acres"] > 0:
            cv = cat.county_value(r)
            bench = (cv.get("value") if cv else None) or state_fre.get(r["state"])
            if bench and bench > 0:
                ppa = r["price"] / r["acres"]
                vs_pct = int(round(((ppa - bench) / bench) * 100.0))
        rows.append([r["id"], r.get("lat"), r.get("lon"), r["state"], r["price"], r["price_kind"], r["acres"],
                     r["status"], 1 if r["available"] else 0, r["title"], r["county_label"], r.get("apn") or "",
                     (r.get("deadline") or "")[:10], 0, vs_pct])
    w.write("data/map.json", json.dumps({"fields": ["id", "lat", "lon", "state", "price", "kind", "acres", "status", "available",
                                                    "title", "county", "apn", "deadline", "direct", "vs_bench_pct"], "rows": rows}, separators=(",", ":")))
    out = io.StringIO()
    cw = csv.writer(out, lineterminator="\n")
    cw.writerow(["id", "source", "agency", "title", "state", "county", "locality", "address", "parcel", "acres", "price",
                 "price_kind", "status", "available", "deadline", "latitude", "longitude", "first_seen", "last_read", "official_url", "page"])
    for r in sorted(cat.listings, key=lambda r: r["id"]):
        cw.writerow([r["id"], r["source"], cat.sources[r["source"]]["agency"], r["title"], r["state"], r["county_label"],
                     r.get("locality", ""), r.get("address", ""), r.get("apn", ""), r["acres"] or "", "" if r["price"] is None else r["price"],
                     r["price_kind"], r["status"], "yes" if r["available"] else "no", r.get("deadline") or "", r.get("lat") or "",
                     r.get("lon") or "", r.get("first_seen") or "", r["checked"], r["url"], config.BASE_URL + cat.listing_path(r)])
    w.write("data/listings.csv", out.getvalue())
    w.write("data/atlas.json", json.dumps(_build_atlas_payload(cat, site), separators=(",", ":")))

    w.page("/data/", site.data_page([
        ("/data/listings.csv", "Every active and recent official listing: facts, status, coordinates, official agency URL"),
        ("/data/map.json", "Compact geospatial point table powering the interactive map"),
        ("/data/atlas.json", "50-state USDA 2010-2026 time series, 3,115 county benchmarks, and national supply analytics"),
        ("/data/sources.json", "Source status: last successful read, counts, failures, and site stats"),
        ("/api/search/?limit=25", "Live JSON search API across official public parcels and direct owner/agent listings"),
        ("/api/concierge/", "Land Agent Acquisition Concierge API ($20 initiation + 10% transfer fee)"),
        ("/api/alerts/", "Saved-Search & Custom Instant Atom/RSS + JSON Land Alert API"),
        ("/openapi.json", "OpenAPI 3.1 reference for the six public Landosaur APIs"),
        ("/data/landosaur-mcp.tgz", "Installable Landosaur MCP server for stdio clients"),
        ("/.well-known/landosaur-agent.json", "Machine-readable AI Agent API schema (search, X-Ray, publish, bid/reserve, alerts, hire Land Agent)"),
        ("/feeds/buy-now.xml", "Atom feed of fixed-price Buy It Now official land parcels"),
        ("/feeds/auctions.xml", "Atom feed of active public land auctions and tax sales"),
    ]), indexable=True, group="core")

    updated = (cat.status.get("checked") or cat.now.strftime("%Y-%m-%d"))[:10]
    new = cat.new()
    cur = cat.current()
    active_sources = {r["source"] for r in cur}
    priced = [r for r in cur if r["price"] is not None]
    state_counts = {}
    for row in cur:
        state_counts[row["state"]] = state_counts.get(row["state"], 0) + 1
    status = dict(cat.status)
    status["sources"] = {}
    for source, info in cat.status.get("sources", {}).items():
        registry = cat.sources.get(source, {})
        public_info = {field: registry[field] for field in ("name", "agency", "state", "url", "about") if field in registry}
        status["sources"][source] = dict(info, **public_info, active_count=cat.active_by_source.get(source, 0),
                                         archived=bool(registry.get("historical_only")))
    status["site"] = {
        "base_url": config.BASE_URL, "listings": len(cat.listings), "current": len(cur),
        "new": len(new), "closing_soon": len(cat.closing()), "guides": len(site.guides),
        "states_tracked": len(cat.states), "states_with_active_listings": len(state_counts),
        "states_priced": len({r["state"] for r in priced}), "priced_listings": len(priced),
        "states_with_benchmarks": len(site.all_states),
        "active_source_feeds": len(active_sources),
        "active_agencies": len({cat.sources[source]["agency"] for source in active_sources}),
        "active_by_state": state_counts,
        "commit": os.environ.get("GITHUB_SHA", ""), "indexable": config.INDEXABLE,
        "indexable_count": len(w.indexable),
    }
    w.write("data/sources.json", json.dumps(status, indent=1, sort_keys=True))

    buy_now_rows = [r for r in cur if r["price_kind"] == "cash"]
    auction_rows = sorted(
        [r for r in cur if r["price_kind"] == "min_bid" or r["status"] in ("auction_open", "auction_terms")],
        key=lambda r: (r.get("deadline") or "9999", 0 if r["price"] is not None else 1, r["id"]),
    )
    w.write("feeds/new.xml", atom("New government land listings | Landosaur", "/feeds/new.xml", new or cur[:80], cat, updated))
    w.write("feeds/buy-now.xml", atom("Buy It Now fixed-price official land | Landosaur", "/feeds/buy-now.xml", buy_now_rows[:100], cat, updated))
    w.write("feeds/auctions.xml", atom("Active public land auctions & tax sales | Landosaur", "/feeds/auctions.xml", auction_rows[:100], cat, updated))
    for st in cat.states.values():
        st_new = [r for r in new if r["state"] == st["code"]]
        st_feed = st_new if st_new else [r for r in st["listings"] if r["available"]][:60]
        w.write("feeds/%s.xml" % st["code"].lower(), atom(
            "Official land listings in %s | Landosaur" % st["name"],
            "/feeds/%s.xml" % st["code"].lower(), st_feed, cat, updated))
    og_default_src = os.path.join(config.SITE_SRC, "og-default.png")
    og_custom_dir = os.path.join(config.SITE_SRC, "og")
    os.makedirs(os.path.join(dist, "og"), exist_ok=True)
    for og_name in ["default.png", "research.png", "new.png", "closing.png"] + ["state-%s.png" % st["code"].lower() for st in cat.states.values()]:
        custom = os.path.join(og_custom_dir, og_name)
        image = custom if os.path.isfile(custom) else og_default_src
        if os.path.isfile(image):
            with open(image, "rb") as fh:
                w.write("og/" + og_name, fh.read())
    write_share_templates(w, cat, updated, new, cur)

    if config.INDEXABLE:
        children = []
        for grp in ("core", "places", "listings"):
            urls = w.indexable_groups.get(grp) or []
            if not urls:
                continue
            rel_sm = "sitemaps/%s.xml" % grp
            w.write(rel_sm, _urlset_xml(urls, updated))
            children.append("/" + rel_sm)
        idx = ['<?xml version="1.0" encoding="UTF-8"?>', '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for cpath in children:
            idx.append("<sitemap><loc>%s</loc><lastmod>%s</lastmod></sitemap>" % (esc(config.BASE_URL + cpath), updated))
        idx.append("</sitemapindex>")
        w.write("sitemap.xml", "\n".join(idx) + "\n")
        w.write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % config.BASE_URL)
    else:
        w.write("robots.txt", "User-agent: *\nDisallow: /\n")

    w.write("llms.txt", build_llms_txt(cat, site, updated))
    w.write("manifest.json", json.dumps({"pages": w.pages, "indexable": sorted(w.indexable), "updated": updated}, sort_keys=True,
                                        separators=(",", ":")))
    w.write(".nojekyll", "")
    w.prune()
    log("built %d files, %d pages (%d indexable: core=%d places=%d listings=%d), %d listings (%d current) into %s" % (
        w.files, len(w.pages), len(w.indexable),
        len(w.indexable_groups["core"]), len(w.indexable_groups["places"]), len(w.indexable_groups["listings"]),
        len(cat.listings), len(cur), dist))
    return w


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    cards_only = "--og-only" in argv
    if cards_only:
        argv.remove("--og-only")
    dist = argv[0] if argv else os.path.join(config.ROOT, "dist")
    if cards_only:
        cat = Catalog()
        updated = (cat.status.get("checked") or cat.now.strftime("%Y-%m-%d"))[:10]
        write_share_templates(Writer(os.path.abspath(dist)), cat, updated, cat.new(), cat.current())
    else:
        build(dist)
    return 0


if __name__ == "__main__":
    sys.exit(main())
