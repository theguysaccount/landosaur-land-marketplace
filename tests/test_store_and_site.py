import datetime
import html as htmllib
import json
import os
import re
import shutil
import tempfile
import unittest

from lando import build, config, refresh, research, store
from lando.model import Catalog
from lando.pages import Site

NOW = datetime.datetime(2026, 11, 26, 12, 0, tzinfo=datetime.timezone.utc)


def listing(i, **kw):
    r = {"id": "stl-%011d" % i, "source": "st-louis-lra", "title": "%d Main St, St. Louis (vacant lot)" % i, "state": "MO",
         "county": "St. Louis city", "locality": "St. Louis", "apn": "%011d" % i, "acres": 0.1, "price": None, "price_kind": "none",
         "offering": "sale", "status": "listed", "deadline": None, "url": "https://www.stlouis-mo.gov/x?parcelId=%d" % i,
         "address": "%d Main St" % i, "lat": 38.6, "lon": -90.2, "geometry": [[[-90.2, 38.6], [-90.2, 38.601], [-90.199, 38.601], [-90.2, 38.6]]],
         "facts": [{"topic": "availability", "value": "Available", "url": "@stl_inventory", "note": "stl_available"}], "tags": []}
    r.update(kw)
    return r


class MergeTest(unittest.TestCase):
    def test_first_read_marks_nothing_new_and_later_arrivals_are_new(self):
        rows, _ = store.merge([], [listing(1), listing(2)], "2026-11-01", True)
        self.assertEqual({r["first_seen"] for r in rows}, {""})
        rows2, _ = store.merge(rows, [listing(1), listing(2), listing(3)], "2026-11-02", True)
        self.assertEqual({r["id"]: r["first_seen"] for r in rows2}["stl-%011d" % 3], "2026-11-02")

    def test_withdrawal_needs_two_complete_reads(self):
        base = [listing(i) for i in range(1, 11)]
        rows, _ = store.merge([], base, "d1", True)
        rows, _ = store.merge(rows, base[:9], "d2", True)
        self.assertEqual(len([r for r in rows if not r["missing"]]), 9)
        self.assertEqual(len(rows), 10)
        rows, notes = store.merge(rows, base[:9], "d3", True)
        self.assertEqual(len(rows), 9)
        self.assertTrue(any("two complete reads" in n for n in notes))

    def test_partial_or_tiny_reads_never_withdraw(self):
        base = [listing(i) for i in range(1, 11)]
        rows, _ = store.merge([], base, "d1", True)
        for day in ("d2", "d3", "d4"):
            rows, _ = store.merge(rows, base[:2], day, True)
        self.assertEqual(len(rows), 10)
        for day in ("d5", "d6"):
            rows, _ = store.merge(rows, base[:9], day, False)
        self.assertEqual(len(rows), 10)


class RotatingUrlTest(unittest.TestCase):
    def test_rotating_links_are_kept_for_a_week(self):
        a = listing(1, url="https://auction.cosl.org/Auction/Listing/AAA", rotating_url=True)
        rows, _ = store.merge([], [a], "2026-11-01", True)
        self.assertEqual((rows[0]["url"], rows[0]["url_date"]), ("https://auction.cosl.org/Auction/Listing/AAA", "2026-11-01"))
        b = listing(1, url="https://auction.cosl.org/Auction/Listing/BBB", rotating_url=True)
        rows, _ = store.merge(rows, [b], "2026-11-05", True)
        self.assertEqual(rows[0]["url"], "https://auction.cosl.org/Auction/Listing/AAA")
        c = listing(1, url="https://auction.cosl.org/Auction/Listing/CCC", rotating_url=True)
        rows, _ = store.merge(rows, [c], "2026-11-09", True)
        self.assertEqual((rows[0]["url"], rows[0]["url_date"]), ("https://auction.cosl.org/Auction/Listing/CCC", "2026-11-09"))
        self.assertNotIn("rotating_url", rows[0])


class RefreshAndBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        # Copy real USDA / guides reference assets into temp data dir so full site builds accurately
        for sub in ("market", "research", "usda"):
            src = os.path.join(config.DATA, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(self.data, sub))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_failing_source_keeps_last_good_data_and_site_builds_with_sitemap_index(self):
        good = {"id": "st-louis-lra", "name": "STL", "agency": "City", "url": "https://x", "state": "MO", "about": "a",
                "run": lambda fetch, now, warn: ([listing(1), listing(2, status="auction_open", price=500.0, price_kind="min_bid",
                                                                    deadline="2026-12-05T00:00:00Z")], {"complete": True})}
        changed, warnings = refresh.run(self.data, now=NOW, log=lambda *a: None, sources=[good], fetcher=object())
        self.assertEqual(changed, ["st-louis-lra"])

        def broken(fetch, now, warn):
            raise RuntimeError("down")
        bad = dict(good, run=broken)
        changed, warnings = refresh.run(self.data, now=NOW + datetime.timedelta(days=1), log=lambda *a: None, sources=[bad], fetcher=object())
        self.assertEqual(changed, [])
        self.assertEqual(len(warnings), 1)
        st = store.load_status(self.data)["sources"]["st-louis-lra"]
        self.assertEqual((st["ok"], st["failures"]), (False, 1))
        self.assertEqual(len(store.load_listings("st-louis-lra", self.data)), 2)

        dist = os.path.join(self.tmp, "dist")
        saved = config.INDEXABLE
        try:
            config.INDEXABLE = False
            w = build.build(os.path.join(self.tmp, "staged"), self.data, now=NOW + datetime.timedelta(days=1), log=lambda *a: None)
            self.assertEqual(w.indexable, [])
            with open(os.path.join(self.tmp, "staged", "robots.txt")) as fh:
                self.assertIn("Disallow: /", fh.read())
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "staged", "sitemap.xml")))

            config.INDEXABLE = True
            w = build.build(dist, self.data, now=NOW + datetime.timedelta(days=1), log=lambda *a: None)
        finally:
            config.INDEXABLE = saved

        # Verify unpriced municipal lot is noindex while priced auction lot IS indexable
        with open(os.path.join(dist, "land", "stl-%011d" % 1, "index.html"), encoding="utf-8") as fh:
            unpriced_page = fh.read()
        self.assertIn("noindex, follow", unpriced_page)
        self.assertIn("It is not an offer", unpriced_page)
        with open(os.path.join(dist, "land", "stl-%011d" % 2, "index.html"), encoding="utf-8") as fh:
            priced_page = fh.read()
        self.assertIn("index, follow", priced_page)

        # Verify Sitemap Index + child sitemaps
        with open(os.path.join(dist, "sitemap.xml"), encoding="utf-8") as fh:
            sitemap_idx = fh.read()
        self.assertIn("<sitemapindex", sitemap_idx)
        self.assertIn("/sitemaps/core.xml", sitemap_idx)
        self.assertIn("/sitemaps/places.xml", sitemap_idx)
        self.assertIn("/sitemaps/listings.xml", sitemap_idx)
        with open(os.path.join(dist, "sitemaps", "core.xml"), encoding="utf-8") as fh:
            core_sm = fh.read()
        for expected_loc in ("/land-for-sale/</loc>", "/land-prices/</loc>", "/land-prices/georgia/</loc>",
                             "/land-prices/texas/</loc>", "/analyze/</loc>", "/research/</loc>", "/research/tax-sales/</loc>"):
            self.assertIn(expected_loc, core_sm)
        with open(os.path.join(dist, "sitemaps", "listings.xml"), encoding="utf-8") as fh:
            list_sm = fh.read()
        self.assertIn("/land/stl-00000000002/</loc>", list_sm)
        self.assertNotIn("/land/stl-00000000001/</loc>", list_sm)

        # Verify homepage FAQPage parity & zero PBN dofollow
        with open(os.path.join(dist, "index.html"), encoding="utf-8") as fh:
            home_html = fh.read()
        self._assert_faq_parity(home_html, expected_count=6, required_types={"Organization", "WebSite", "SoftwareApplication", "Dataset", "FAQPage"})
        self._assert_zero_pbn_dofollow(home_html)

        # Verify /research/ page JSON-LD, FAQ parity & guide links
        with open(os.path.join(dist, "research", "index.html"), encoding="utf-8") as fh:
            research_html = fh.read()
        self.assertIn("/research/tax-sales/", research_html)
        self._assert_faq_parity(research_html, expected_count=6, required_types={"Organization", "BreadcrumbList", "Article", "Dataset", "FAQPage"})
        self._assert_zero_pbn_dofollow(research_html)

        # Verify /land-prices/georgia/ renders SVG chart, county table & FAQ parity
        with open(os.path.join(dist, "land-prices", "georgia", "index.html"), encoding="utf-8") as fh:
            ga_html = fh.read()
        self.assertIn("trend-svg", ga_html)
        self.assertIn("FAQPage", ga_html)
        self._assert_zero_pbn_dofollow(ga_html)

    def _assert_faq_parity(self, doc, expected_count, required_types):
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', doc, re.S)
        self.assertTrue(blocks, "expected JSON-LD script block")
        found_types = set()
        ld_qas = []
        for raw in blocks:
            parsed = json.loads(raw)
            nodes = parsed.get("@graph", [parsed])
            for node in nodes:
                if "@type" in node:
                    found_types.add(node["@type"])
                if node.get("@type") == "FAQPage":
                    for item in node.get("mainEntity", []):
                        ld_qas.append((item["name"], item["acceptedAnswer"]["text"]))
        self.assertTrue(required_types.issubset(found_types), "missing JSON-LD types: %s" % (required_types - found_types))
        html_matches = re.findall(
            r'<details class="faq-item"><summary>(.*?)</summary><p>(.*?)</p></details>',
            doc, re.S,
        )
        html_qas = [(htmllib.unescape(q).strip(), htmllib.unescape(a).strip()) for q, a in html_matches]
        self.assertEqual(len(html_qas), expected_count)
        self.assertEqual(html_qas, ld_qas)

    def _assert_zero_pbn_dofollow(self, doc):
        portfolio_hosts = ("land-index-fund", "index.grounded.to", "america.co", "democracys.org", "rsio.org")
        for match in re.finditer(r'<a\b[^>]*href="(https?://[^"]+)"[^>]*>', doc, re.I):
            tag, href = match.group(0), match.group(1)
            if any(host in href for host in portfolio_hosts):
                self.assertIn("nofollow", tag.lower(), "portfolio link missing nofollow: %s" % tag)

    def test_real_catalog_benchmarks_50_states_and_29_guides(self):
        cat = Catalog(config.DATA, now=NOW)
        b = research.compute_benchmarks(cat)
        self.assertGreater(b["active_count"], 10000)
        self.assertGreaterEqual(b["state_count"], 6)
        self.assertGreaterEqual(b["agency_count"], 8)
        self.assertGreaterEqual(len(b["findings"]), 8)
        self.assertEqual(len(b["research_faqs"]), 6)
        self.assertEqual(len(b["home_faqs"]), 6)
        site = Site(cat)
        self.assertEqual(len(site.all_states), 50)
        self.assertEqual(len(site.guides), 29)
        doc = site.research()
        self._assert_faq_parity(doc, expected_count=6, required_types={"Organization", "BreadcrumbList", "Article", "Dataset", "FAQPage"})
        self._assert_zero_pbn_dofollow(doc)

    def test_stale_sources_leave_the_map(self):
        good = {"id": "st-louis-lra", "name": "STL", "agency": "City", "url": "https://x", "state": "MO", "about": "a",
                "run": lambda fetch, now, warn: ([listing(1)], {"complete": True})}
        refresh.run(self.data, now=NOW, log=lambda *a: None, sources=[good], fetcher=object())
        fresh = Catalog(self.data, now=NOW + datetime.timedelta(days=2))
        self.assertEqual(len(fresh.current()), 1)
        stale = Catalog(self.data, now=NOW + datetime.timedelta(days=config.CURRENT_DAYS + 1))
        self.assertEqual(len(stale.current()), 0)


if __name__ == "__main__":
    unittest.main()
