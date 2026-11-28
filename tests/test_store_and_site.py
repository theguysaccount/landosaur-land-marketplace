import datetime
import html as htmllib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from lando import adapters, build, config, refresh, research, store
from lando.model import Catalog
from lando.pages import Site
from scripts import check_dist

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
    def test_validator_checks_links_and_owner_words_in_the_entire_dossier(self):
        document = '<link href="/site.css"><img src="/parcel.png"><a href="/land/">Land</a>'
        self.assertCountEqual(check_dist.document_links(document), ["/site.css", "/land/", "/parcel.png"])
        for content in ('<p>Owner</p>', '<meta content="Prior Owner">', "&#79;wner", "O&#x77;ne&#114;"):
            self.assertTrue(check_dist.mentions_owner(content), content)
        for content in ("&#9744; Parcel card", "HomeOwnership", "landowner", "&#112;arcel"):
            self.assertFalse(check_dist.mentions_owner(content), content)

    def test_validator_scans_dossiers_and_the_rest_of_dist(self):
        dist = Path(self.tmp) / "verification"
        names = {"index.html", "land/index.html", "land/apn-01/index.html",
                 "land/apn-01/attachments/survey.txt", "land/apn-02/index.html",
                 "data/example.json", "_og/example.png"}
        for name in names:
            path = dist / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.assertEqual(check_dist.inventory_files(dist), names)

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

    def test_metadata_catalog_keeps_current_listing_fields_and_routes(self):
        row = listing(1)
        store.save_listings(row["source"], [row], self.data)
        store.save_status({"sources": {row["source"]: {"last_success": NOW.isoformat()}}}, self.data)
        full = Catalog(self.data, now=NOW)
        metadata = Catalog(self.data, now=NOW, include_geometry=False)
        full_row, = full.current()
        metadata_row, = metadata.current()
        self.assertEqual(metadata_row, {key: value for key, value in full_row.items() if key != "geometry"})
        self.assertEqual(metadata.listing_path(metadata_row), full.listing_path(full_row))

    def test_unverified_offers_and_elapsed_local_close_dates_are_inactive(self):
        archived = listing(1, source="delaware-in", price=500, price_kind="min_bid",
                           status="auction_terms", deadline="2026-12-05T00:00:00Z")
        archived["facts"] = [{"topic": "minimum_bid", "value": "$500", "url": "="},
                             {"topic": "auction_item", "value": "Item #1", "url": "="},
                             {"topic": "parcel_number", "value": "00123456", "url": "="}]
        dated = listing(2, source="salt-lake-county-surplus", status="auction_terms",
                        offer_close_date="2026-11-26")
        proposal = listing(3, source="california-dgs", status="proposal_open",
                           deadline="2026-11-27T00:00:00Z")
        for row in (archived, dated, proposal):
            store.save_listings(row["source"], [row], self.data)
        store.save_status({"sources": {r["source"]: {"last_success": "2026-11-26T12:00:00Z"}
                                       for r in (archived, dated, proposal)}}, self.data)
        still_open = datetime.datetime(2026, 11, 27, 4, tzinfo=datetime.timezone.utc)
        catalog = Catalog(self.data, now=still_open)
        self.assertEqual([r["id"] for r in catalog.current()], [dated["id"]])
        self.assertEqual(catalog.by_id[archived["id"]]["status"], "availability_unverified")
        self.assertIsNone(catalog.by_id[archived["id"]]["price"])
        self.assertEqual([fact["topic"] for fact in catalog.by_id[archived["id"]]["facts"]], ["parcel_number"])
        self.assertEqual(Catalog(self.data, now=still_open + datetime.timedelta(hours=8)).current(), [])

    def test_auction_with_only_a_date_stops_at_start_of_local_sale_day(self):
        row = listing(1, source="conejos-co-treasurer-sale", status="auction_terms", auction_day="2026-12-02")
        store.save_listings(row["source"], [row], self.data)
        store.save_status({"sources": {row["source"]: {"last_success": "2026-11-28T12:00:00Z"}}}, self.data)
        start = datetime.datetime(2026, 12, 2, 7, tzinfo=datetime.timezone.utc)
        current, = Catalog(self.data, now=start - datetime.timedelta(seconds=1)).current()
        self.assertIsNone(current["deadline"])
        self.assertEqual(current["closes_at_ms"], int(start.timestamp() * 1000))
        self.assertEqual(Catalog(self.data, now=start).current(), [])

    def test_deadline_displays_source_local_calendar_day_and_closes_at_exact_instant(self):
        row = listing(1, source="salt-lake-county-surplus", status="proposal_open", deadline="2026-12-16T00:00:00Z")
        store.save_listings(row["source"], [row], self.data)
        store.save_status({"sources": {row["source"]: {"last_success": "2026-12-15T12:00:00Z"}}}, self.data)
        cutoff = datetime.datetime(2026, 12, 16, tzinfo=datetime.timezone.utc)
        active, = Catalog(self.data, now=cutoff - datetime.timedelta(seconds=1)).current()
        self.assertEqual(active["deadline_date"], "2026-12-15")
        self.assertEqual(active["deadline_display"], "2026-12-15 17:00 MST")
        self.assertEqual(active["deadline"], row["deadline"])
        self.assertEqual(active["closes_at_ms"], int(cutoff.timestamp() * 1000))
        self.assertEqual(Catalog(self.data, now=cutoff).current(), [])

    def test_static_budget_preserves_dated_auction_and_large_dossiers(self):
        rows = [
            listing(1, available=True, price=500),
            listing(2, available=True, acres=1.2),
            listing(3, available=True, status="auction_terms", offering="auction", auction_day="2026-12-02"),
            listing(4, available=True),
        ]
        self.assertEqual(build.static_dossier_ids(rows, budget=3), {row["id"] for row in rows[:3]})

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

    def test_real_catalog_benchmarks_50_states_and_state_guides(self):
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
        self.assertEqual(len(site.guides), 41)
        self.assertEqual(set(site.state_guides), {"TX", "FL", "GA", "CA", "AR", "AZ", "MI", "OH", "PA", "WI", "UT", "OR"})
        doc = site.research()
        self._assert_faq_parity(doc, expected_count=6, required_types={"Organization", "BreadcrumbList", "Article", "Dataset", "FAQPage"})
        self._assert_zero_pbn_dofollow(doc)

    def test_new_agency_does_not_change_an_unrelated_parcel_page(self):
        parcel = listing(1, price=1250, price_kind="asking")
        store.save_listings(parcel["source"], [parcel], self.data)
        store.save_status({"sources": {parcel["source"]: {"last_success": "2026-11-26T12:00:00Z"}}}, self.data)
        before = Catalog(self.data, now=NOW)
        expected = Site(before).listing(before.by_id[parcel["id"]])
        added = {"id": "another-agency", "agency": "Agency for Another State", "state": "NE"}
        with patch.object(adapters, "SOURCES", [*adapters.SOURCES, added]):
            after = Catalog(self.data, now=NOW)
            doc = Site(after).listing(after.by_id[parcel["id"]])
        self.assertEqual(doc, expected)
        self.assertIn('href="/sources/">Official agency directory', doc)
        self.assertIn('data-official-source="1"', doc)
        self.assertIn("It is not an offer", doc)

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
