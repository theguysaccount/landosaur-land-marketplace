"""Guard a built site before it is deployed. Exit 1 with a list of problems, or 0.

    python3 scripts/check_dist.py [dist]

Every page: title, description, canonical, one h1, the not-an-offer notice, valid JSON-LD, and a robots meta that
matches the indexing policy (pages that duplicate the live original are always noindex).
Every internal link resolves. The sitemap lists exactly the indexable pages. Every listing in data/ has a page,
and every listing page links to an official source over https. No previous-owner field leaks into the output.
Indexing follows the fleet convention: SITE_INDEXABLE unset keeps the whole copy out of search.
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

HREF = re.compile(r'(?:href|src)="([^"]+)"')
OFFICIAL = ("stlouis-mo.gov", "cosl.org", "wisconsin.gov", "alaskamentalhealthtrust.org", "alaska.gov")


def resolve(dist, base, url):
    if url.startswith(config.BASE_URL):
        url = base + url[len(config.BASE_URL):]
    if not url.startswith(base + "/"):
        return None
    path = url[len(base):].split("#")[0].split("?")[0] or "/"
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
            if re.search(r"\bowner\b", doc, re.I) and "Owner" in re.sub(r"(?s)<[^>]+>", " ", doc):
                problems.append("%s: mentions an owner field" % rel)
            for url in HREF.findall(doc):
                target = resolve(dist, base, html.unescape(url))
                if target and not os.path.exists(target):
                    problems.append("%s: broken internal link %s" % (rel, url))
            if rel.startswith("land/") and rel.count("/") == 2:
                button = re.search(r'<a class="button" href="([^"]+)"', doc)
                if not button or not button.group(1).startswith("https://") or not any(h in button.group(1) for h in OFFICIAL):
                    problems.append("%s: no official https source link" % rel)
    for t, where in titles.items():
        if len(where) > 1:
            problems.append("duplicate title %r on %s" % (t, ", ".join(where[:3])))
    # Fleet convention: SITE_INDEXABLE unset -> nothing indexable; true -> only the pages the original lacks.
    expected = {"/new/", "/closing-soon/"} if config.INDEXABLE else set()
    if indexable != expected:
        problems.append("indexable pages %s, expected %s" % (sorted(indexable)[:5], sorted(expected)))
    robots = open(os.path.join(dist, "robots.txt"), encoding="utf-8").read()
    smap = os.path.join(dist, "sitemap.xml")
    if config.INDEXABLE:
        locs = {l[len(config.BASE_URL):] for l in re.findall(r"<loc>([^<]+)</loc>", open(smap, encoding="utf-8").read())}
        if locs != indexable:
            problems.append("sitemap lists %d URLs but %d pages are indexable" % (len(locs), len(indexable)))
        if "Sitemap: %s/sitemap.xml" % config.BASE_URL not in robots:
            problems.append("robots.txt does not point at the sitemap")
    elif os.path.exists(smap) or "Disallow: /" not in robots:
        problems.append("staged copy must have robots.txt Disallow: / and no sitemap")
    cat = Catalog(data_dir)
    for r in cat.listings:
        if not os.path.exists(os.path.join(dist, "land", r["slug"], "index.html")):
            problems.append("listing %s has no page" % r["id"])
    csv_text = open(os.path.join(dist, "data", "listings.csv"), encoding="utf-8").read()
    if "Owner" in csv_text.splitlines()[0]:
        problems.append("listings.csv has an owner column")
    print("checked %d HTML files, %d listings, %d indexable pages: %d problems" % (pages, len(cat.listings), len(indexable), len(problems)))
    for p in problems[:200]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist")))
