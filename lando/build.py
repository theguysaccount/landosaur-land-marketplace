"""Build the static site into dist/ from data/.

    python3 -m lando.build [dist]

Generates:
  - Interactive Zillow-for-Land explorer (/), national directory (/land-for-sale/), state & county hubs
  - 50-State Land Price Observatory (/land-prices/* — 56 pages backed by USDA NASS 2010-2026 + 3,115 counties)
  - Research & Benchmarks (/research/) + 29 source-cited buyer guides (/research/<slug>/)
  - Interactive Valuation, Financing & Off-Grid Power Workbench (/analyze/)
  - Individual GIS parcel dossiers (/land/<id>/)
  - CSV/JSON downloads, Atom feeds, Sitemap Index (/sitemap.xml -> /sitemaps/{core,places,listings}.xml),
    robots.txt, llms.txt, IndexNow key file, share cards, and manifest.json.
"""
import csv
import hashlib
import io
import json
import os
import shutil
import sys

from . import adapters, config, research
from .model import Catalog, STATE_NAMES
from .pages import DINO, Site, acres_text, esc, listing_is_indexable, price_line

STATIC = ["style.css", "map.js", "listing.js", "tables.js", "analyze.js", "favicon.svg", "mascot.png"]


class Writer(object):
    def __init__(self, dist):
        self.dist = dist
        self.pages = {}
        self.indexable = []
        self.indexable_groups = {"core": [], "places": [], "listings": []}
        self.files = 0

    def write(self, rel, data, page_path=None, indexable=False, group="core"):
        full = os.path.join(self.dist, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        raw = data.encode("utf-8") if isinstance(data, str) else data
        with open(full, "wb") as fh:
            fh.write(raw)
        self.files += 1
        if page_path is not None:
            self.pages[page_path] = hashlib.sha1(raw).hexdigest()[:16]
            if indexable:
                self.indexable.append(page_path)
                self.indexable_groups.setdefault(group, []).append(page_path)

    def page(self, path, html_, indexable=False, group="core"):
        rel = path.strip("/")
        self.write((rel + "/" if rel else "") + "index.html", html_, path, indexable and config.INDEXABLE, group=group)


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


def build_llms_txt(cat, site, updated):
    cur = cat.current()
    b = research.compute_benchmarks(cat)
    states = sorted(cat.states.values(), key=lambda s: s["name"])
    base = config.BASE_URL
    lines = [
        "# Landosaur — Official U.S. Land Map, 50-State Land Price Observatory & Valuation Workbench",
        "",
        ("> Landosaur maps official public-agency land offerings across U.S. states and counties "
         "(tax-sale auctions, surplus state trust land, municipal land banks, and state redevelopment notices), "
         "paired with a 50-state USDA/FHFA Land Price Observatory (2010-%d across 3,115 counties), "
         "%d source-cited buyer research guides, and a deterministic land deal & off-grid power analyzer." % (
             site.market.latest_year, len(site.guides))),
        "",
        "## Key Platform Capabilities",
        "",
        "- **Live Official Inventory Map** (%s/): %s active official offerings across %d tracked states and %d agencies (checked daily), with split-screen map/list filtering, saved shortlists, 4-parcel side-by-side comparison, GIS outlines, USGS aerial/topo tiles, FEMA NFHL flood hazard overlays, and a distance ruler." % (
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
        s = cat.status.get("sources", {}).get(src["id"], {})
        count = s.get("count") or 0
        lines.append("- **%s** (%s) — %s (%s %s)" % (
            src["agency"], STATE_NAMES.get(src["state"], src["state"]), src["about"],
            "{:,}".format(count), "listing" if count == 1 else "listings"))
    lines.extend([
        "",
        "## Primary Hub URLs",
        "",
        "- [Interactive Land Map](%s/)" % base,
        "- [Land for Sale by State (50-State Directory)](%s/land-for-sale/)" % base,
        "- [50-State Land Price Observatory](%s/land-prices/)" % base,
        "- [50-State Land Price Rankings](%s/land-prices/states/)" % base,
        "- [Cheapest Official Land Per Acre](%s/land-prices/cheapest-land-per-acre/)" % base,
        "- [U.S. Land Price History (2010-%d)](%s/land-prices/history/)" % (site.market.latest_year, base),
        "- [Land Deal, Electricity & Valuation Analyzer](%s/analyze/)" % base,
        "- [US Public-Agency Benchmarks & 29 Buyer Guides](%s/research/)" % base,
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
    lines.extend([
        "",
        "## Machine-Readable Data & Discovery",
        "",
        "- [Listings CSV](%s/data/listings.csv)" % base,
        "- [Map JSON](%s/data/map.json)" % base,
        "- [Sources Status JSON](%s/data/sources.json)" % base,
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


def build(dist, data_dir=None, now=None, log=print):
    cat = Catalog(data_dir, now)
    site = Site(cat)
    if os.path.isdir(dist):
        shutil.rmtree(dist)
    os.makedirs(dist)
    w = Writer(dist)
    for name in STATIC:
        os.makedirs(os.path.join(dist, "assets"), exist_ok=True)
        shutil.copy(os.path.join(config.SITE_SRC, name), os.path.join(dist, "assets", name))
    shutil.copytree(os.path.join(config.SITE_SRC, "vendor"), os.path.join(dist, "assets", "vendor"))
    with open(os.path.join(config.SITE_SRC, "indexnow-key.txt")) as fh:
        key = fh.read().strip()
    w.write("%s.txt" % key, key)

    # Core hubs
    w.page("/", site.home(), indexable=True, group="core")
    w.page("/land-for-sale/", site.land_for_sale_index(), indexable=True, group="core")
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
    for r in cat.listings:
        w.page(cat.listing_path(r), site.listing(r), indexable=listing_is_indexable(r), group="listings")

    # Map JSON & CSV downloads
    rows = []
    for r in cat.listings:
        rows.append([r["id"], r.get("lat"), r.get("lon"), r["state"], r["price"], r["price_kind"], r["acres"],
                     r["status"], 1 if r["available"] else 0, r["title"], r["county_label"], r.get("apn") or "",
                     (r.get("deadline") or "")[:10]])
    w.write("data/map.json", json.dumps({"fields": ["id", "lat", "lon", "state", "price", "kind", "acres", "status", "available",
                                                    "title", "county", "apn", "deadline"], "rows": rows}, separators=(",", ":")))
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

    w.page("/data/", site.data_page([
        ("/data/listings.csv", "Every active and recent official listing: facts, status, coordinates, official agency URL"),
        ("/data/map.json", "Compact geospatial point table powering the interactive map"),
        ("/data/sources.json", "Source status: last successful read, counts, failures, and site stats"),
    ]), indexable=True, group="core")

    status = dict(cat.status)
    status["site"] = {
        "base_url": config.BASE_URL, "listings": len(cat.listings), "current": len(cat.current()),
        "new": len(cat.new()), "closing_soon": len(cat.closing()), "guides": len(site.guides),
        "states_tracked": len(cat.states), "states_priced": len(site.all_states),
        "commit": os.environ.get("GITHUB_SHA", ""), "indexable": config.INDEXABLE,
        "indexable_count": len(w.indexable),
    }
    w.write("data/sources.json", json.dumps(status, indent=1, sort_keys=True))

    updated = (cat.status.get("checked") or cat.now.strftime("%Y-%m-%d"))[:10]
    new = cat.new()
    w.write("feeds/new.xml", atom("New government land listings | Landosaur", "/feeds/new.xml", new, cat, updated))
    for st in cat.states.values():
        w.write("feeds/%s.xml" % st["code"].lower(), atom(
            "New government land listings in %s | Landosaur" % st["name"],
            "/feeds/%s.xml" % st["code"].lower(), [r for r in new if r["state"] == st["code"]], cat, updated))

    cur = cat.current()
    og_default_src = os.path.join(config.SITE_SRC, "og-default.png")
    og_custom_dir = os.path.join(config.SITE_SRC, "og")
    os.makedirs(os.path.join(dist, "og"), exist_ok=True)
    for og_name in ["default.png", "research.png", "new.png", "closing.png"] + ["state-%s.png" % st["code"].lower() for st in cat.states.values()]:
        custom = os.path.join(og_custom_dir, og_name)
        if os.path.exists(custom):
            shutil.copy(custom, os.path.join(dist, "og", og_name))
        elif os.path.exists(og_default_src):
            shutil.copy(og_default_src, os.path.join(dist, "og", og_name))
    w.write("_og/default.html", og_card(
        "Find, map, and value official land for sale",
        "%s listings · 50-state land prices" % "{:,}".format(len(cur)),
        "Official agencies, GIS flood & aerial maps, valuation workbench. Not an offer to sell."))
    w.write("_og/research.html", og_card(
        "US Public-Agency Land Benchmarks & 29 Buyer Guides",
        "%s active official offerings" % "{:,}".format(len(cur)),
        "Computed directly from official public agency inventories. Zero invented prices."))
    w.write("_og/new.html", og_card(
        "New government land listings",
        "%s in the last %d days" % ("{:,}".format(len(new)), config.NEW_DAYS),
        "Checked daily from official sources. Atom feeds by state."))
    w.write("_og/closing.html", og_card(
        "Land auctions closing soon",
        "%s deadlines in the next %d days" % ("{:,}".format(len(cat.closing())), config.CLOSING_DAYS),
        "Official sources, checked daily. Confirm cutoffs with the agency."))
    for st in cat.states.values():
        n = sum(1 for r in st["listings"] if r["available"])
        w.write("_og/state-%s.html" % st["code"].lower(), og_card(
            "Government and auction land in %s" % st["name"],
            "%s current listings" % "{:,}".format(n),
            "Every listing links directly to the agency's own page."))

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
    log("built %d files, %d pages (%d indexable: core=%d places=%d listings=%d), %d listings (%d current) into %s" % (
        w.files, len(w.pages), len(w.indexable),
        len(w.indexable_groups["core"]), len(w.indexable_groups["places"]), len(w.indexable_groups["listings"]),
        len(cat.listings), len(cur), dist))
    return w


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    build(argv[0] if argv else os.path.join(config.ROOT, "dist"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
