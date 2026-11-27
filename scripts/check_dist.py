"""Guard a built site before it is deployed. Exit 1 with a list of problems, or 0.

    python3 scripts/check_dist.py [dist]

Validates every page (title, description, canonical, 1 h1, not-an-offer notice, valid JSON-LD,
working internal links, unique titles), official https agency links and zero previous-owner leaks
on listing pages/CSV, and exact parity between indexable pages and the sitemap index + child sitemaps.
"""
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
import html
import json
import os
import re
import sys
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lando import config  # noqa: E402
from lando.model import Catalog  # noqa: E402
from lando.pages import listing_is_indexable  # noqa: E402

HREF = re.compile(r'(?:href|src)="([^"]+)"')
OFFICIAL = {
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
    "phdcphila.org", "atlas.phila.gov", "clevelandohio.gov", "dallascityhall.com",
    "southsuburbanlandbank.org", "newburghcommunitylandbank.org", "saltlakecounty.gov", "muncielandbank.org",
    "hctax.net", "gblba.org", "dot.ca.gov", "mass.gov", "lakota-nd.com", "broward.org", "princetonmn.org",
    "burlingtoniowa.org", "dmcgis.com", "desotoclerk.com", "greenburghny.com", "aarauctions.com", "cityofrochester.gov",
    "city.milwaukee.gov", "detroitmi.gov", "co.lucas.oh.us", "co.sauk.wi.us", "hokecounty.net", "wsdot.wa.gov", "itascacountymn.gov", "valencia.nm.us", "tax.newmexico.gov", "stlouiscountymn.gov", "fnsb.gov",
}


TITLE = re.compile(r"<title>(.*?)</title>", re.S)
DESCRIPTION = re.compile(r'<meta name="description" content="[^"]{20,}"')
ROBOTS = re.compile(r'<meta name="robots" content="([^"]+)"')
JSON_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
TAGS = re.compile(r"<[^>]+>")
OWNER = re.compile(r"\bOwner\b")
OFFICIAL_LINK = re.compile(r'<a[^>]*data-official-source="1"[^>]*href="([^"]+)"')


@lru_cache(maxsize=32768)
def resolve(base, raw_url):
    url = html.unescape(raw_url)
    if url.startswith(config.BASE_URL + "/"):
        url = base + url[len(config.BASE_URL):]
    if not url.startswith(base + "/"):
        return None
    path = url[len(base):].split("#", 1)[0].split("?", 1)[0]
    if path.startswith("/api/"):
        return None
    return path.lstrip("/") + ("index.html" if path.endswith("/") else "")


@lru_cache(maxsize=128)
def official_host(host):
    labels = host.split(".")
    return any(".".join(labels[i:]) in OFFICIAL for i in range(len(labels) - 1))


def official_source(link):
    try:
        url = urlsplit(html.unescape(link))
        host = url.hostname or ""
    except ValueError:
        return False
    return url.scheme == "https" and official_host(host)


def init_worker(dist, files, base):
    global _dist, _files, _base
    _dist, _files, _base = dist, files, base


def validate(rel):
    if rel == "404.html":
        return "", False, []
    with open(os.path.join(_dist, rel), encoding="utf-8") as fh:
        doc = fh.read()
    problems = []
    match = TITLE.search(doc)
    title = match.group(1) if match else ""
    if not title.strip():
        problems.append("no title")
    if not DESCRIPTION.search(doc):
        problems.append("missing description")
    if '<link rel="canonical" href="%s' % config.BASE_URL not in doc:
        problems.append("no canonical")
    h1 = doc.count("<h1")
    if h1 != 1:
        problems.append("%d h1 elements" % h1)
    if "It is not an offer" not in doc:
        problems.append("no not-an-offer notice")
    robots = ROBOTS.search(doc)
    index = bool(robots and robots.group(1).startswith("index"))
    for block in JSON_LD.findall(doc):
        try:
            json.loads(block)
        except ValueError as exc:
            problems.append("bad JSON-LD (%s)" % exc)
    for url in HREF.findall(doc):
        target = resolve(_base, url)
        if target and target not in _files:
            problems.append("broken internal link %s" % url)
    if rel.startswith("land/") and rel.count("/") == 2:
        if ("Owner" in doc or "&#" in doc) and OWNER.search(html.unescape(TAGS.sub(" ", doc))):
            problems.append("mentions an owner field")
        official_link = OFFICIAL_LINK.search(doc)
        if not official_link or not official_source(official_link.group(1)):
            problems.append("no official https source link")
    return title, index, problems


def main(dist, data_dir=None):
    dist = os.path.abspath(dist)
    base = config.base_path()
    problems, titles, indexable = [], {}, set()
    files = set()
    for dirpath, _, names in os.walk(dist):
        prefix = dirpath[len(dist) + 1:]
        files.update(os.path.join(prefix, name) for name in names)
    pages = sorted(rel for rel in files if rel.endswith(".html") and not rel.startswith("_og/"))
    with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 1, 6), initializer=init_worker,
                             initargs=(dist, files, base)) as pool:
        for rel, (title, index, issues) in zip(pages, pool.map(validate, pages, chunksize=128)):
            problems.extend("%s: %s" % (rel, issue) for issue in issues)
            if title:
                titles.setdefault(title, []).append(rel)
            if index:
                indexable.add("/" + rel.removesuffix("index.html"))

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
        for req_path in ("/", "/land-under-5000/", "/land-under-10000/", "/acreage-for-sale/", "/deals/", "/tax-sales/", "/xray/", "/list/", "/direct/", "/services/", "/land-atlas/", "/land-for-sale/", "/land-prices/", "/land-prices/states/", "/analyze/", "/research/", "/new/", "/closing-soon/", "/sources/", "/data/", "/about/"):
            if req_path not in indexable:
                problems.append("core hub not indexable: %s" % req_path)
    elif os.path.exists(smap) or "Disallow: /" not in robots_txt:
        problems.append("staged copy must have robots.txt Disallow: / and no sitemap")

    cat = Catalog(data_dir)
    for r in cat.listings:
        if os.path.join("land", r["slug"], "index.html") not in files:
            problems.append("listing %s has no page" % r["id"])
        elif config.INDEXABLE and listing_is_indexable(r) and cat.listing_path(r) not in indexable:
            problems.append("priced/deadline listing %s should be indexable" % r["id"])
    csv_text = open(os.path.join(dist, "data", "listings.csv"), encoding="utf-8").read()
    if "Owner" in csv_text.splitlines()[0]:
        problems.append("listings.csv has an owner column")
    print("checked %d HTML files, %d listings, %d indexable pages: %d problems" % (len(pages), len(cat.listings), len(indexable), len(problems)))
    for p in problems[:200]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist")))
