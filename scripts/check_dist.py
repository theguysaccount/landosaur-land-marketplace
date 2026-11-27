"""Guard a built site before it is deployed. Exit 1 with a list of problems, or 0.

    python3 scripts/check_dist.py [dist]

Validates every page (title, description, canonical, 1 h1, not-an-offer notice, valid JSON-LD,
working internal links, unique titles), official https agency links and zero previous-owner leaks
on listing pages/CSV, and exact parity between indexable pages and the sitemap index + child sitemaps.
"""
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lando import config  # noqa: E402
from lando.model import Catalog  # noqa: E402
from lando.pages import listing_is_indexable  # noqa: E402

HREF = re.compile(r'(?:href|src)="([^"]+)"')
OFFICIAL = (
    "stlouis-mo.gov", "cosl.org", "wisconsin.gov", "alaskamentalhealthtrust.org",
    "alaska.gov", "buildingdetroit.org", "kclandbank.org", "dgs.ca.gov",
    "chicago.gov", "pghlandbank.org", "louisvilleky.gov", "lucascountylandbank.org",
    "lacounty.gov", "bcpa.net", "utah.gov",
    "albanycountylandbank.org", "orangecountyfl.net", "lascruces.gov",
    "baltimorecity.gov", "bigspringtx.gov",
    "kingcounty.gov", "charlottenc.gov", "cantonga.gov", "sanmiguelcountyco.gov",
    "navajocountyaz.gov", "publicsurplus.com", "brla.gov", "chnj.gov", "orlando.gov",
    "delawarecounty.in.gov", "millelacs.mn.gov", "ottertailcounty.gov", "rva.gov",
    "montgomeryal.gov", "cityofwaterlooiowa.com", "wycokck.org", "snco.gov",
    "wilmingtonde.gov", "hartfordct.gov", "cityofomaha.org", "bluefieldwv.gov",
    "memphistn.gov", "warwickri.gov", "boston.gov",
    "albanycountywy.gov", "oklahoma.gov", "sos.ms.gov", "horrycountysc.gov",
    "portland.gov", "mauicounty.gov", "lasvegasnevada.gov", "peterboroughnh.gov",
    "cityofyankton.org", "burleigh.gov", "vcgi.vermont.gov", "dnrc.mt.gov",
    "cityofboise.org", "auburnmaine.gov", "portlandmaine.gov",
)


def resolve(dist, base, url):
    if url.startswith(config.BASE_URL):
        url = base + url[len(config.BASE_URL):]
    if not url.startswith(base + "/"):
        return None
    path = url[len(base):].split("#")[0].split("?")[0] or "/"
    if path.startswith("/api/"):
        return None
    rel = path.lstrip("/")
    if path.endswith("/"):
        rel += "index.html"
    return os.path.join(dist, rel)


def main(dist, data_dir=None):
    base = config.base_path()
    problems, titles, pages, indexable = [], {}, 0, set()
    for dirpath, _, files in os.walk(dist):
        for name in files:
            if not name.endswith(".html") or "/_og" in dirpath:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, dist)
            doc = open(full, encoding="utf-8").read()
            pages += 1
            if rel == "404.html":
                continue
            t = re.search(r"<title>(.*?)</title>", doc, re.S)
            if not t or not t.group(1).strip():
                problems.append("%s: no title" % rel)
            else:
                titles.setdefault(t.group(1), []).append(rel)
            if not re.search(r'<meta name="description" content="[^"]{20,}"', doc):
                problems.append("%s: missing description" % rel)
            if '<link rel="canonical" href="%s' % config.BASE_URL not in doc:
                problems.append("%s: no canonical" % rel)
            if doc.count("<h1") != 1:
                problems.append("%s: %d h1 elements" % (rel, doc.count("<h1")))
            if "It is not an offer" not in doc:
                problems.append("%s: no not-an-offer notice" % rel)
            robots = re.search(r'<meta name="robots" content="([^"]+)"', doc)
            if robots and robots.group(1).startswith("index"):
                indexable.add("/" + rel[:-len("index.html")] if rel.endswith("index.html") else "/" + rel)
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', doc, re.S):
                try:
                    json.loads(block)
                except ValueError as exc:
                    problems.append("%s: bad JSON-LD (%s)" % (rel, exc))
            for url in HREF.findall(doc):
                target = resolve(dist, base, html.unescape(url))
                if target and not os.path.exists(target):
                    problems.append("%s: broken internal link %s" % (rel, url))
            if rel.startswith("land/") and rel.count("/") == 2:
                visible = re.sub(r"(?s)<[^>]+>", " ", doc)
                if re.search(r"\bOwner\b", visible):
                    problems.append("%s: mentions an owner field" % rel)
                button = re.search(r'<a class="button" href="([^"]+)"', doc)
                if not button or not button.group(1).startswith("https://") or not any(h in button.group(1) for h in OFFICIAL):
                    problems.append("%s: no official https source link" % rel)

    for t, where in titles.items():
        if len(where) > 1:
            problems.append("duplicate title %r on %s" % (t, ", ".join(where[:3])))

    robots_txt = open(os.path.join(dist, "robots.txt"), encoding="utf-8").read()
    smap = os.path.join(dist, "sitemap.xml")
    if config.INDEXABLE:
        if not os.path.exists(smap):
            problems.append("missing sitemap.xml")
        else:
            sm_body = open(smap, encoding="utf-8").read()
            locs = set()
            if "<sitemapindex" in sm_body:
                children = re.findall(r"<loc>([^<]+)</loc>", sm_body)
                if not children:
                    problems.append("sitemap index lists no child sitemaps")
                for child_url in children:
                    if not child_url.startswith(config.BASE_URL + "/"):
                        problems.append("child sitemap wrong host: %s" % child_url)
                        continue
                    cpath = os.path.join(dist, child_url[len(config.BASE_URL) + 1:])
                    if not os.path.exists(cpath):
                        problems.append("missing child sitemap %s" % cpath)
                        continue
                    if os.path.getsize(cpath) > 50 * 1024 * 1024:
                        problems.append("child sitemap exceeds 50MB: %s" % cpath)
                    c_locs = [l[len(config.BASE_URL):] for l in re.findall(r"<loc>([^<]+)</loc>", open(cpath, encoding="utf-8").read())]
                    if len(c_locs) > 50000:
                        problems.append("child sitemap exceeds 50,000 URLs: %s" % cpath)
                    locs.update(c_locs)
            else:
                locs = {l[len(config.BASE_URL):] for l in re.findall(r"<loc>([^<]+)</loc>", sm_body)}
            if locs != indexable:
                problems.append("sitemaps list %d URLs but %d pages are indexable (diff sample: %s)" % (
                    len(locs), len(indexable), sorted(locs ^ indexable)[:5]))
        if "Sitemap: %s/sitemap.xml" % config.BASE_URL not in robots_txt:
            problems.append("robots.txt does not point at the sitemap")
        for req_path in ("/", "/xray/", "/list/", "/direct/", "/land-for-sale/", "/land-prices/", "/land-prices/states/", "/analyze/", "/research/", "/new/", "/closing-soon/", "/sources/", "/data/", "/about/"):
            if req_path not in indexable:
                problems.append("core hub not indexable: %s" % req_path)
    elif os.path.exists(smap) or "Disallow: /" not in robots_txt:
        problems.append("staged copy must have robots.txt Disallow: / and no sitemap")

    cat = Catalog(data_dir)
    for r in cat.listings:
        if not os.path.exists(os.path.join(dist, "land", r["slug"], "index.html")):
            problems.append("listing %s has no page" % r["id"])
        elif config.INDEXABLE and listing_is_indexable(r) and cat.listing_path(r) not in indexable:
            problems.append("priced/deadline listing %s should be indexable" % r["id"])
    csv_text = open(os.path.join(dist, "data", "listings.csv"), encoding="utf-8").read()
    if "Owner" in csv_text.splitlines()[0]:
        problems.append("listings.csv has an owner column")
    print("checked %d HTML files, %d listings, %d indexable pages: %d problems" % (pages, len(cat.listings), len(indexable), len(problems)))
    for p in problems[:200]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist")))
