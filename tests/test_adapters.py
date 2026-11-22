import datetime
import unittest

from lando import adapters

NOW = datetime.datetime(2026, 11, 22, 12, 0, tzinfo=datetime.timezone.utc)

AVAILABLE = ("ParcelId,Address,WARD,NeighborhoodName,Usage,PropertyType,Side lot Eligible?,Irregular_Lot,SQFT\n"
             "00209030000,10   ASHLEY ST ,8,Near North Riverfront,Vacant Lot,Lot,,Yes,53051\n"
             "44419170000,4141   LEXINGTON AV ,12,Greater Ville,Vacant Lot,Lot,Yes,,4465\n"
             "11111111111,1 MAIN ST,1,Downtown,Residential,Building,,,1000\n"
             "22222222222,2 MAIN ST,1,Downtown,Vacant Lot,Lot,,,1000\n"
             "33333333333,3 MAIN ST,1,Downtown,Vacant Lot,Lot,,,1000\n"
             "33333333333,3 MAIN ST,1,Downtown,Vacant Lot,Lot,,,2000\n")
INVENTORY = ("ParcelId,Parcel_Status,Property_Source\n00209030000,Available,Tax Suit\n44419170000,Available,Tax Suit\n"
             "11111111111,Available,\n22222222222,Unavailable,\n33333333333,Available,\n")


class StLouisTest(unittest.TestCase):
    def test_only_available_vacant_lots_without_conflicts(self):
        warnings = []
        rows = adapters.parse_st_louis(AVAILABLE, INVENTORY, warnings.append)
        self.assertEqual(sorted(r["apn"] for r in rows), ["00209030000", "44419170000"])
        self.assertTrue(any("listed twice" in w for w in warnings))
        r = [x for x in rows if x["apn"] == "00209030000"][0]
        self.assertIsNone(r["price"])
        self.assertEqual(r["price_kind"], "none")
        self.assertAlmostEqual(r["acres"], round(53051 / 43560.0, 4))
        self.assertTrue(r["url"].startswith("https://www.stlouis-mo.gov/"))
        self.assertEqual(r["status"], "listed")

    def test_changed_columns_are_a_structure_error(self):
        with self.assertRaises(adapters.StructureError):
            adapters.parse_st_louis("A,B\n1,2\n", INVENTORY, lambda w: None)


class ArkansasTest(unittest.TestCase):
    ROW = {"Owner": "SOMEONE PRIVATE", "CoSLCountyName": "FULTON", "CoSLParcelNumber": "627-31057-000", "Acreage": 0.0,
           "Section": "5", "Start": None, "End": None, "NumberOfBids": 0, "CurrentBid": 0.0, "StartingBid": 393.29,
           "CoSLPropertyId": 833473, "ListingToken": "TKBrnVeCmjYrXM42VjGf3VY7Fmhwfk7QI4GYqLazhEE",
           "Added": "2026-11-17T07:00:02.524218", "Township": "20N", "Range": "5W"}

    def test_listing_drops_owner_names_and_reads_status(self):
        r = adapters.arkansas_listing(dict(self.ROW), NOW)
        self.assertNotIn("SOMEONE", repr(r))
        self.assertEqual((r["status"], r["price"], r["price_kind"], r["county"]), ("auction_terms", 393.29, "min_bid", "Fulton"))
        self.assertIsNone(r["acres"])
        self.assertEqual(r["listed_date"], "2026-11-17")
        self.assertTrue(r["url"].endswith(self.ROW["ListingToken"]))

    def test_deadlines(self):
        open_ = adapters.arkansas_listing(dict(self.ROW, Start="2026-11-20T10:00:00", End="2026-11-29T02:00:00"), NOW)
        self.assertEqual(open_["status"], "auction_open")
        self.assertEqual(open_["deadline"], "2026-11-29T08:00:00Z")
        closed = adapters.arkansas_listing(dict(self.ROW, End="2026-11-01T02:00:00"), NOW)
        self.assertEqual(closed["status"], "auction_closed")

    def test_feed_shape_is_checked(self):
        with self.assertRaises(adapters.StructureError):
            adapters.parse_arkansas_rows({"Data": [], "Errors": "x", "Total": 0})
        rows, total = adapters.parse_arkansas_rows({"Data": [self.ROW], "Total": 1})
        self.assertEqual(total, 1)


WI_PAGE = """<h2>Latest Sealed Bid Auction</h2><p>auction closing of December 1, 2026</p>
<div class="surplus-land-container"><div class="surplus-land-header1">Forest County</div><div class="surplus-land-header2">Double Bend</div>
<div class="surplus-land-header3">S2706</div><div class="surplus-land-column">Tax Parcel ID: 004-00278-0000</div>
<div class="surplus-land-column">This 80 acre parcel has no legal access.</div><div class="surplus-land-column sl-money-column">$116,000</div>
<div class="surplus-land-column"><a href="/Archive/Land/S2706-Forest.pdf">View Map</a></div></div>
<div class="surplus-land-container-evenrow" style="display&#58;none;"><div class="surplus-land-header1">[county]</div><div class="surplus-land-header2">[name]</div><div class="surplus-land-header3">[T#]</div></div>
<h2>List of Current/Recent Surplus Property Sales (Private Sale Properties)</h2>
<div class="surplus-land-container"><div class="surplus-land-header1">Price County</div><div class="surplus-land-header2">Timber Road</div>
<div class="surplus-land-header3">S2105</div><div class="surplus-land-column">Tax Parcel ID: 1</div><div class="surplus-land-column">Approximately 40 acres.</div>
<div class="surplus-land-column sl-money-column">$12,950</div></div>
<div class="surplus-land-container"><div class="surplus-land-header1">Iron County</div><div class="surplus-land-header2">Gone</div>
<div class="surplus-land-header3">S0001</div><div class="surplus-land-column">x</div><div class="surplus-land-column">y</div>
<div class="surplus-land-column sl-money-column">$1,000 SOLD</div></div>"""


class WisconsinTest(unittest.TestCase):
    def test_programs_prices_and_skips(self):
        rows = {r["id"]: r for r in adapters.parse_wisconsin(WI_PAGE, NOW, lambda w: None)}
        self.assertEqual(sorted(rows), ["wi-s2105", "wi-s2706"])
        a = rows["wi-s2706"]
        self.assertEqual((a["status"], a["price_kind"], a["price"], a["acres"]), ("auction_open", "min_bid", 116000.0, 80.0))
        self.assertTrue(a["deadline"].startswith("2026-12-02"))
        self.assertTrue(any(f["topic"] == "access" for f in a["facts"]))
        p = rows["wi-s2105"]
        self.assertEqual((p["status"], p["price_kind"], p["acres"]), ("listed", "cash", 40.0))


TRUST_PAGE = """<div class="left-side"><h1 class="main-heading">OTC: Sitka &#8211; Middle Island (MHT 9100501) *NEW*</h1> Intro text <br />
<strong>Location:</strong> Sitka</p><strong>Subdivision:</strong> Middle Island East</p><strong>MHT Number:</strong> 9100501</p>
<strong>Purchase Price:</strong> $114,000.00</p><strong>Acres:</strong> 2.139</p><strong>Road Access:</strong> No</p>
<a href="https://alaskamentalhealthtrust.org/news/parcel/otc-mht-9100501/" class="button-submit">Learn More</a></div><div class="right-side"></div>"""

DNR_PAGE = """<section class="card js-parcel-card" data-auction="499" data-parcel="4" data-acres="25.6600" data-price="60710.000000"
 data-subd="North Fork Micro Ag" data-region="Southcentral" data-resident-requirement="no" data-road-access="no" data-program="OTC"
 data-adl="234471" id="parcel-499-4"><p>Purchase Price $60,710</p></section>"""


class AlaskaTest(unittest.TestCase):
    def test_trust_cards(self):
        rows = adapters.parse_trust(TRUST_PAGE, lambda w: None)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["price"], r["acres"], r["locality"], r["status"]), (114000.0, 2.139, "Sitka", "listed"))
        self.assertEqual(r["title"], "Sitka – Middle Island (MHT 9100501)")

    def test_dnr_cards(self):
        rows = adapters.parse_dnr(DNR_PAGE, "", NOW, lambda w: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["price_kind"], rows[0]["status"], rows[0]["acres"]), ("cash", "listed", 25.66))
        with self.assertRaises(adapters.StructureError):
            adapters.parse_dnr("<html></html>", "", NOW, lambda w: None)


class GeometryTest(unittest.TestCase):
    def test_centroid_and_outline_link(self):
        r = {"id": "stl-1", "source": "st-louis-lra", "apn": "00209030000", "url": "https://x", "facts": [], "lat": None, "lon": None}
        adapters.apply_geometry(r, [[[-90.0, 38.0], [-90.0, 38.002], [-89.998, 38.002], [-89.998, 38.0], [-90.0, 38.0]]], "@outline", "City")
        self.assertAlmostEqual(r["lat"], 38.001, places=4)
        self.assertAlmostEqual(r["lon"], -89.999, places=4)
        self.assertIn("ParcelId%3D%2700209030000%27", adapters.expand_url(r, "@outline"))
        self.assertEqual(adapters.expand_url(r, "="), "https://x")


if __name__ == "__main__":
    unittest.main()
