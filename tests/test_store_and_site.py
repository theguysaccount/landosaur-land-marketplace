import datetime
import os
import shutil
import tempfile
import unittest

from lando import build, config, refresh, store

NOW = datetime.datetime(2026, 11, 22, 12, 0, tzinfo=datetime.timezone.utc)


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
            rows, _ = store.merge(rows, base[:2], day, True)     # far smaller than before
        self.assertEqual(len(rows), 10)
        for day in ("d5", "d6"):
            rows, _ = store.merge(rows, base[:9], day, False)    # partial read
        self.assertEqual(len(rows), 10)


class RefreshAndBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_failing_source_keeps_last_good_data_and_site_builds(self):
        good = {"id": "st-louis-lra", "name": "STL", "agency": "City", "url": "https://x", "state": "MO", "about": "a",
                "run": lambda fetch, now, warn: ([listing(1), listing(2, status="auction_open", price=500.0, price_kind="min_bid",
                                                                    deadline="2026-12-01T00:00:00Z")], {"complete": True})}
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
        w = build.build(dist, self.data, now=NOW + datetime.timedelta(days=1), log=lambda *a: None)
        self.assertEqual(sorted(w.indexable), ["/closing-soon/", "/new/"] if not config.INDEX_DUPLICATES else sorted(w.indexable))
        page = open(os.path.join(dist, "land", "stl-%011d" % 1, "index.html"), encoding="utf-8").read()
        self.assertIn("noindex", page)
        self.assertIn("It is not an offer", page)
        self.assertIn("https://www.stlouis-mo.gov/x?parcelId=1", page)
        closing = open(os.path.join(dist, "closing-soon", "index.html"), encoding="utf-8").read()
        self.assertIn("stl-%011d" % 2, closing)
        sitemap = open(os.path.join(dist, "sitemap.xml"), encoding="utf-8").read()
        self.assertIn("/new/</loc>", sitemap)
        self.assertNotIn("/land/", sitemap)

    def test_stale_sources_leave_the_map(self):
        good = {"id": "st-louis-lra", "name": "STL", "agency": "City", "url": "https://x", "state": "MO", "about": "a",
                "run": lambda fetch, now, warn: ([listing(1)], {"complete": True})}
        refresh.run(self.data, now=NOW, log=lambda *a: None, sources=[good], fetcher=object())
        from lando.model import Catalog
        fresh = Catalog(self.data, now=NOW + datetime.timedelta(days=2))
        self.assertEqual(len(fresh.current()), 1)
        stale = Catalog(self.data, now=NOW + datetime.timedelta(days=config.CURRENT_DAYS + 1))
        self.assertEqual(len(stale.current()), 0)


if __name__ == "__main__":
    unittest.main()
