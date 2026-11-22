"""Build the static site into dist/ from data/.

    python3 -m lando.build [dist]

Pages, the map data, CSV and JSON downloads, Atom feeds, sitemap.xml (indexable pages only), robots.txt, the
IndexNow key file, share-card sources (_og/*.html, rendered by scripts/og.py) and manifest.json (a hash per page,
for telling IndexNow only about indexable pages that changed).
"""
import csv
import datetime
import hashlib
import io
import json
import os
import shutil
import sys

from . import adapters, config
from .model import Catalog, STATE_NAMES
from .pages import DINO, Site, acres_text, esc, money, price_line

STATIC = ["style.css", "map.js", "listing.js", "tables.js", "favicon.svg", "mascot.png"]


class Writer(object):
    def __init__(self, dist):
        self.dist = dist
        self.pages = {}
        self.indexable = []
        self.files = 0

    def write(self, rel, data, page_path=None, indexable=False):
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

    def page(self, path, html_, indexable=False):
        rel = path.strip("/")
        self.write((rel + "/" if rel else "") + "index.html", html_, path, indexable or config.INDEX_DUPLICATES)


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
            'body{background:#f6f8f2;color:#193c2c;font-family:"Arial Rounded MT Bold",system-ui,-apple-system,"Segoe UI",Roboto,"DejaVu Sans",sans-serif;'
            'display:flex;flex-direction:column;justify-content:space-between;padding:60px 70px;box-sizing:border-box;'
            'background-image:radial-gradient(circle at 90%% 20%%,#e3f6bb 0,#e3f6bb 220px,transparent 221px)}'
            '.b{display:flex;align-items:center;gap:18px;font-size:34px;font-weight:700;color:#236b43}.b svg{width:72px;height:72px}'
            'h1{font-size:62px;line-height:1.05;margin:0;max-width:900px;letter-spacing:-.01em}.v{font-size:40px;color:#236b43;font-weight:700}'
            '.s{font-size:26px;color:#667568}</style></head><body><div class="b">%s Landosaur</div><div><h1>%s</h1><p class="v">%s</p></div>'
            '<p class="s">%s</p></body></html>') % (DINO, esc(title), esc(big), esc(sub))


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

    w.page("/", site.home())
    w.page("/new/", site.new(), indexable=True)
    w.page("/closing-soon/", site.closing(), indexable=True)
    w.page("/sources/", site.sources_page())
    w.page("/about/", site.about())
    w.write("404.html", site.not_found())
    for st in cat.states.values():
        w.page(cat.state_path(st), site.state(st))
        for c in st["counties"].values():
            w.page(cat.county_path(st, c), site.county(st, c))
            for g in c["groups"]:
                w.page(cat.county_path(st, c) + g["slug"] + "/", site.county(st, c, g))
    for r in cat.listings:
        w.page(cat.listing_path(r), site.listing(r))

    # map data: every listing, current or not; the page filters
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
    status = dict(cat.status)
    status["site"] = {"base_url": config.BASE_URL, "listings": len(cat.listings), "current": len(cat.current()),
                      "new": len(cat.new()), "closing_soon": len(cat.closing()), "commit": os.environ.get("GITHUB_SHA", ""),
                      "index_duplicates": config.INDEX_DUPLICATES}
    w.write("data/sources.json", json.dumps(status, indent=1, sort_keys=True))
    w.page("/data/", site.data_page([("/data/listings.csv", "Every listing: facts, status, official link"),
                                     ("/data/map.json", "Compact listing points used by the map"),
                                     ("/data/sources.json", "Source status: last successful read, counts, failures")]))

    updated = (cat.status.get("checked") or cat.now.strftime("%Y-%m-%d"))[:10]
    new = cat.new()
    w.write("feeds/new.xml", atom("New government land listings | Landosaur", "/feeds/new.xml", new, cat, updated))
    for st in cat.states.values():
        w.write("feeds/%s.xml" % st["code"].lower(), atom("New government land listings in %s | Landosaur" % st["name"],
                                                          "/feeds/%s.xml" % st["code"].lower(), [r for r in new if r["state"] == st["code"]], cat, updated))

    cur = cat.current()
    w.write("_og/default.html", og_card("Government and auction land for sale, on one map", "%s listings from official sources" % "{:,}".format(len(cur)),
                                        "City lots, tax-sale parcels and state land. Not an offer to sell."))
    w.write("_og/new.html", og_card("New government land listings", "%s in the last %d days" % ("{:,}".format(len(new)), config.NEW_DAYS),
                                    "Checked daily from official sources. Atom feeds by state."))
    w.write("_og/closing.html", og_card("Land auctions closing soon", "%s deadlines in the next %d days" % ("{:,}".format(len(cat.closing())), config.CLOSING_DAYS),
                                        "Official sources, checked daily. Confirm cutoffs with the agency."))
    for st in cat.states.values():
        n = sum(1 for r in st["listings"] if r["available"])
        w.write("_og/state-%s.html" % st["code"].lower(), og_card("Government and auction land in %s" % st["name"],
                                                                  "%s current listings" % "{:,}".format(n), "Every listing links to the agency's own page."))

    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in sorted(w.indexable):
        sm.append("<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (esc(config.BASE_URL + p), updated))
    sm.append("</urlset>")
    w.write("sitemap.xml", "\n".join(sm) + "\n")
    w.write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % config.BASE_URL)
    w.write("manifest.json", json.dumps({"pages": w.pages, "indexable": sorted(w.indexable), "updated": updated}, sort_keys=True,
                                        separators=(",", ":")))
    w.write(".nojekyll", "")
    log("built %d files, %d pages (%d indexable), %d listings (%d current) into %s" % (
        w.files, len(w.pages), len(w.indexable), len(cat.listings), len(cur), dist))
    return w


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    build(argv[0] if argv else os.path.join(config.ROOT, "dist"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
