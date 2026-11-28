import datetime
import html
import json
import unittest
from unittest.mock import patch

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

    def test_side_lot_price_requires_county_eligibility_and_lot_area(self):
        available = AVAILABLE.replace("Yes,,4465", "Yes,,3999")
        rows = {r["apn"]: r for r in adapters.parse_st_louis(available, INVENTORY, lambda w: None, 100)}
        self.assertIsNone(rows["00209030000"]["price"])
        self.assertEqual((rows["44419170000"]["price"], rows["44419170000"]["price_kind"]), (100, "application"))
        self.assertIsNone(adapters.parse_st_louis(AVAILABLE, INVENTORY, lambda w: None, 100)[1]["price"])


class ActiveSaleDirectoryTest(unittest.TestCase):
    def test_san_joaquin_uses_current_ungrouped_sale_and_vacant_assessment(self):
        report = (
            "San Joaquin County\nMarch 17-18, 2027 Tax Sale List\nAssessee  Minimum Bid  Comments\n"
            "1  117-170-090-000  DEF-210-000-001  PRIVATE NAME  NO SITUS\n"
            "2  117-235-110-000  DEF-210-000-002  PRIVATE NAME     $  2,500.00\n"
            "3  139-060-280-000  DEF-210-000-003  PRIVATE NAME     $  5,000.00  Redeemed 11/20/26\n"
            "4  137-180-080-000  DEF-210-000-004  PRIVATE NAME     See Note 1\n"
            "Note 1 - Item numbers 4 and 5 will be offered together.\n"
        )
        fetch = unittest.mock.Mock()
        fetch.text.return_value = (
            '<a href="/docs/auction/report.pdf">March 2027 Auction List (11-20-2026)</a>'
            ' Date of Auction: March 17-18, 2027'
        )
        vacancy = {"APN": "11717009", "USECODE": "2A", "RETIRE_CODE": 0, "VALUE_ROLL_YEAR": "2026",
                   "LAND_VALUE": 59000, "STRUCTURE_VALUE": 0, "IMPROVEMENT_VALUE": 0, "FIXED_EQUIP_VALUE": 0,
                   "TREE_VINE_VALUE": 0, "PERS_PROP_VALUE": 0, "LANDSIZE_SQFT": 9300}
        building = dict(vacancy, APN="11723511", IMPROVEMENT_VALUE=20)
        features = [{"attributes": item} for item in (vacancy, building)]
        with patch.object(adapters, "pdf_text", return_value=report), patch.object(
            adapters, "_arcgis_query", return_value=features
        ) as query:
            rows, meta = adapters.san_joaquin_ca_auction(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual(meta["upstream_total"], 4)
        self.assertEqual((row["apn"], row["price"], row["offer_close_date"]), ("117-170-090-000", None, "2027-03-18"))
        self.assertNotIn("PRIVATE NAME", json.dumps(row))
        self.assertNotIn("13718008", query.call_args.args[2])
        self.assertNotIn("Assessee", query.call_args.args[3])
        self.assertEqual(adapters.parse_san_joaquin_auction(report, "March 17-18, 2027")[0]["11723511"][2], 2500)

    def test_ketchikan_requires_borough_roster_broker_and_vacant_assessment(self):
        fetch = unittest.mock.Mock()
        borough = f'Borough Properties &amp; Lands for Sale <a href="{adapters.KETCHIKAN_LIST_PATH}">List</a> www.alpinerealestateak.com'
        broker = (
            '<mbb-property-item data-id="ak3_25295" data-url="/listing-details/ak3_25295--Lot-7/">'
            '<span data-field="property-status">Active</span><span data-field="price">$1.148m</span>'
            'Lot 7 hosts 337,702 SF or 7.75 acres of wooded undeveloped land. '
            'Sold as surplus lands by the Ketchikan Gateway Borough. Alpine Real Estate'
            '</mbb-property-item>'
        )
        fetch.text.side_effect = {adapters.KETCHIKAN_LAND: borough, adapters.KETCHIKAN_BROKER: broker}.__getitem__
        roster = ("BOROUGH LAND SALES\nReal Estate Listed Properties\nList Price\n"
                  "313710002600 337,702 7.750 Betton View, Lot 7 RS $1,148,000\n")
        assessor = {"attributes": {"Parcel_Num": "313710002600", "PropUse": "VACANT", "Apr_Imps": 0, "Apr_Imps1": 0,
                                   "Apr_Land_V": 579600, "Total_Appr": 579600, "Year_Built": 0, "No_Units": 0,
                                   "Total_Area": 0, "Asse_Year1": 2026}}
        with patch.object(adapters, "pdf_text", return_value=roster):
            with patch.object(adapters, "_arcgis_query", return_value=[assessor]) as query:
                rows, _ = adapters.alaska_ketchikan_surplus(fetch, NOW, self.fail)
                row, = rows
                self.assertEqual((row["apn"], row["price"], row["acres"]), ("313710002600", 1148000, 7.75))
                self.assertNotIn("Owner_Name", query.call_args.args[3])
                assessor["attributes"]["Apr_Imps"] = 100
                self.assertEqual(adapters.alaska_ketchikan_surplus(fetch, NOW, self.fail)[0], [])
        self.assertEqual(adapters.parse_ketchikan_broker(broker.replace(">Active<", ">Under Contract<")), {})

    def test_alaska_university_matches_active_land_offers_to_current_details(self):
        header = "parcel_number ,name,location,sale_type,acres,price,parcel_page,land_sale_lease,land_status\n"
        base = "CB.SS.0001,Silver Springs Terrace,Silver Springs,Over-The-Counter Land Sale Program,1.99,45000,"
        path = "/ualand/land/sale/silver-springs-terrace/CB.SS.0001.php"
        active = base + path + ",otc_sale,active\n"
        sold = active.replace("CB.SS.0001", "CB.SS.0002").replace(",active", ",sold")
        lease = active.replace("CB.SS.0001", "CB.SS.0003").replace("otc_sale", "landlease")
        rows = adapters.parse_ua_sale_feed(header + active + sold + lease)
        item, = rows.values()
        page = ("<h1>CB.SS.0001</h1> Minimum Offer: $45,000 Start Offer Process "
                "An undeveloped lot. Location: Silver Springs, Alaska Acreage: 1.990 "
                "Over-The-Counter Land Sale Purchase Terms and Conditions: at or above the Minimum Price")
        row = adapters.parse_ua_sale_detail(item, page)
        self.assertEqual((row["price"], row["acres"], row["price_kind"]), (45000, 1.99, "min_bid"))
        self.assertEqual(row["locality"], "Silver Springs")
        self.assertIsNone(adapters.parse_ua_sale_detail(item, page.replace("45,000", "42,500")))
        self.assertIsNone(adapters.parse_ua_sale_detail(item, page.replace("An undeveloped lot.", "Sale pending.")))
        self.assertIsNone(adapters.parse_ua_sale_detail(item, page.replace("An undeveloped lot.", "Existing house.")))
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = [
            '<script src="ualand.js"></script> Land Listings',
            'var gsheet = "https://docs.google.com/spreadsheets/d/test/edit#gid=1"',
            header + active + sold + lease,
            page,
        ]
        outline = {"attributes": {"Property_Number": "CB.SS.0001", "Acres": "1.990"},
                   "geometry": {"rings": [[[-134.5, 58.3], [-134.499, 58.3], [-134.5, 58.301], [-134.5, 58.3]]]}}
        with patch.object(adapters, "_arcgis_query", return_value=[outline]) as query:
            rows, _ = adapters.alaska_university_otc(fetch, NOW, self.fail)
            self.assertTrue(rows[0]["geometry"])
            self.assertEqual(query.call_args.args[3], "Property_Number,Acres")

    def test_lincoln_county_sale_ignores_past_bid_and_requires_current_vacancy(self):
        roster = (
            "The property listed below is available for private purchase until sold.\n"
            "MINIMUM BID @ LAST AUCTION\n"
            "R254816 08-10-19-DA 100 Lincoln City R-1 0.41 acres 10/15/2026\n"
            "R344448 08-10-19-DA 142 Lincoln City A-C 2.07 acres 10/15/2026\n"
            "8 R486160 11-10-14-BC 201 Elk City examples A-C 0.19 acres 10/15/2026 $4,000\n"
            "17 R521169 13-12-36-AC 3401 Waldport SW Fehrenbacher Drive RR-2 0.31 acres 10/15/2026 $117,740\n"
            "*20 R505139 14-12-27-AD 2502 Yachats 80 8th Street R-1 0.11 acres 10/15/2026 $300,000\n"
        )
        current = (
            'Property Status A Active Map Number 11-10-14-BC-00201-00 Property Use 950: EXEMPT COUNTY VACANT LAND'
            ' Owner Name LINCOLN COUNTY Mailing Address'
            '<table id="row_tblValueHistoryDataRP"><tr><td>2027 (In Process)</td>'
            '<td>$0</td><td>$17,120</td><td>$17,120</td></tr></table>'
        )
        improved = current.replace("11-10-14-BC-00201-00", "13-12-36-AC-03401-00").replace("$0", "$40,540")
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = {
            adapters.LINCOLN_OR_LAND: f'Tax Foreclosed Property for Sale <a href="{adapters.LINCOLN_OR_ROSTER}">List</a>',
            adapters.LINCOLN_OR_TERMS: "All available properties are for sale as cash only",
            adapters.LINCOLN_OR_ASSESSOR + "R486160": current,
            adapters.LINCOLN_OR_ASSESSOR + "R521169": improved,
        }.__getitem__
        outline = {"attributes": {"MapTaxlot": "11-10-14-BC-00201-00", "EFFECTV_DT": "2026"},
                   "geometry": {"rings": [[[-123.9, 44.6], [-123.91, 44.62], [-123.92, 44.6], [-123.9, 44.6]]]}}
        with patch.object(adapters, "pdf_text", return_value=roster), patch.object(adapters, "_arcgis_query", return_value=[outline]):
            rows, info = adapters.lincoln_or_tax_foreclosed(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual(info["upstream_total"], 5)
        self.assertEqual((row["apn"], row["acres"], row["price"], row["locality"]), ("R486160", 0.19, None, "Elk City"))
        self.assertTrue(row["geometry"])
        self.assertNotIn("Owner", json.dumps(row))
        self.assertFalse(adapters.lincoln_or_is_vacant(current.replace("2027", "2025"), "11-10-14-BC-00201-00", 2026))

    def test_florence_requires_current_city_lot_and_exact_vacant_tax_account(self):
        fetch = unittest.mock.Mock()
        fixture_map = b"%PDF- visually reviewed availability fixture"
        map_path = "/DocumentCenter/View/456/Lots"
        fetch.text.return_value = f'Pacific View Business Park 11 remaining that are available for sale <a href="{map_path}">Lots</a>'
        fetch.bytes.return_value = fixture_map
        records = [
            {"attributes": {"MAPTAXLOT": "1812224201002", "PROPACCT": "1772530", "AscendAcres": "0.27  ",
                            "IMPVAL": 0, "LANDVAL": 51591, "BLDGTYPE": None, "NUMACCNTS": 1},
             "geometry": {"rings": [[[-124.111, 43.991], [-124.110, 43.991], [-124.110, 43.992],
                                    [-124.111, 43.991]]]}},
            {"attributes": {"MAPTAXLOT": "1812221300300", "PROPACCT": "1620952", "AscendAcres": "2.11",
                            "IMPVAL": 0, "LANDVAL": 352608, "BLDGTYPE": "Warehouse", "NUMACCNTS": 1}},
            {"attributes": {"MAPTAXLOT": "1812221300900", "PROPACCT": "different", "AscendAcres": "0.75",
                            "IMPVAL": 0, "LANDVAL": 145413, "BLDGTYPE": None, "NUMACCNTS": 1}},
            {"attributes": {"MAPTAXLOT": "1812221300200", "PROPACCT": "1620945", "AscendAcres": "3.20",
                            "IMPVAL": 0, "LANDVAL": 200000, "BLDGTYPE": None, "NUMACCNTS": 1}},
        ]
        digest = adapters.hashlib.sha256(fixture_map).hexdigest()
        with patch.object(adapters, "FLORENCE_OR_MAPS", {map_path: digest}):
            with patch.object(adapters, "_arcgis_query", return_value=records) as query:
                rows, info = adapters.florence_or_business_park(fetch, NOW, self.fail)
                row, = rows
                self.assertEqual(info, {"complete": True, "upstream_total": 11})
                self.assertEqual((row["apn"], row["acres"], row["price"]), ("1812224201002", 0.27, None))
                self.assertTrue(row["geometry"])
                self.assertIn("'CITY OF FLORENCE'", query.call_args.args[2])
                self.assertNotIn("OWNNAME", query.call_args.args[3])
                fetch.bytes.return_value = b"new map"
                warnings = []
                self.assertEqual(adapters.florence_or_business_park(fetch, NOW, warnings.append)[0], [])
                self.assertEqual(len(warnings), 1)
                query.assert_called_once()

    def test_fulton_tax_deed_requires_reviewed_notice_and_exact_vacant_tax_record(self):
        fetch = unittest.mock.Mock()
        fetch.text.return_value = f'Sheriff’s Tax Deed <a href="{adapters.FULTON_GA_DECEMBER_ROSTER}">Latest sale</a>'
        fetch.bytes.return_value = b"%PDF- verified notice fixture"
        geo = [
            {"attributes": {"ParcelID": "13 003100020608", "Address": "0 CATALINA CIR",
                            "LUCode": "100", "LivUnits": 0, "LandAcres": 0.5778}},
            {"attributes": {"ParcelID": "13 003300010649", "Address": "0 GREEN MOUNTAIN TRL",
                            "LUCode": "100", "LivUnits": 1, "LandAcres": 0.5383}},
            {"attributes": {"ParcelID": "14 003000010095", "Address": "0 OTHER STREET",
                            "LUCode": "100", "LivUnits": 0, "LandAcres": 0.41}},
        ]
        with patch.object(adapters, "arcgis_query", return_value=("https://services1.arcgis.com/exact", geo)) as query:
            self.assertEqual(adapters.fulton_ga_tax_deed(fetch, NOW, self.fail)[0], [])
            query.assert_not_called()
            digest = adapters.hashlib.sha256(fetch.bytes.return_value).hexdigest()
            with patch.object(adapters, "FULTON_GA_DECEMBER_SHA", digest):
                rows, _ = adapters.fulton_ga_tax_deed(fetch, NOW, self.fail)
                row, = rows
                self.assertEqual((row["apn"], row["price"], row["deadline"]),
                                 ("13 003100020608", None, "2026-12-01T15:00:00Z"))
                at_sale = datetime.datetime(2026, 12, 1, 15, tzinfo=datetime.timezone.utc)
                self.assertEqual(adapters.fulton_ga_tax_deed(fetch, at_sale, self.fail)[0], [])

    def test_palmer_uses_the_exact_auction_minimum_and_local_deadline(self):
        fetch = unittest.mock.Mock()
        page = ('Town Properties Available for Purchase <h3>Land Auction: Country Lane</h3>'
                'Parcel ID: 14-17-10, Title Ref.: 1691/178 20,000 Square Foot Parcel Vacant Land '
                'Sold free of taxes Date: Tuesday, December 1, 2026 Time: 11:00 AM '
                'Location: Town Administration Building Bidder Registration: 10:30 AM '
                'Minimum Bid: $12,500 Certified funds required. Recording cost $155.')
        fetch.text.return_value = page
        rows, _ = adapters.palmer_ma_land_auction(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual((row["apn"], row["price"], row["price_kind"], row["acres"]),
                         ("14-17-10", 12500, "min_bid", 0.4591))
        self.assertEqual(row["deadline"], "2026-12-01T16:00:00Z")
        fetch.text.return_value = page + " Land auction has been cancelled."
        self.assertEqual(adapters.palmer_ma_land_auction(fetch, NOW, self.fail)[0], [])

    def test_north_logan_lists_the_offered_portion_and_expires_at_noon(self):
        page = ('<dt>Event End Date &amp; Time</dt><dd>December 8, 2026 12:00 PM</dd>'
                '<dd class="agenda">INVITATION TO BID to Purchase LAND (Portion of Parcel 04-273-8001)\n'
                'Parcel Tax ID: Portion of 04-273-8001\nAcreage: approximately 0.70\n'
                'Sealed Bids will be received at the North Logan City offices until 12:00 pm (noon) '
                'on Tuesday, December 8, 2026.</dd>')
        fetch = unittest.mock.Mock()
        fetch.text.return_value = page
        rows, info = adapters.north_logan_ut_surplus(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual(info["upstream_total"], 1)
        self.assertEqual((row["apn"], row["acres"], row["price"], row["geometry"]),
                         ("Portion of 04-273-8001", 0.70, None, None))
        self.assertEqual((row["offering"], row["status"]), ("auction", "auction_open"))
        self.assertTrue(adapters.STATUS[row["status"]][1])
        self.assertEqual(row["deadline"], "2026-12-08T19:00:00Z")
        at_close = datetime.datetime(2026, 12, 8, 19, tzinfo=datetime.timezone.utc)
        self.assertEqual(adapters.north_logan_ut_surplus(fetch, at_close, self.fail)[0], [])
        fetch.text.return_value = page.replace("December 8, 2026 12:00 PM", "December 8, 2026 01:00 PM")
        with self.assertRaises(adapters.StructureError):
            adapters.north_logan_ut_surplus(fetch, NOW, self.fail)

    def test_south_suburban_uses_available_lots_only(self):
        def tr(pid, address, kind, status):
            return ("<tr><td><a>%s</a></td><td>%s</td><td>Joliet</td>"
                    "<td>%s</td><td>%s</td><td></td></tr>") % (pid, address, kind, status)
        page = (
            '<table id="parcel-list-table"><thead><tr><th>Parcel Number</th><th>Property Type</th></tr></thead>'
            + tr("30-07-15-221-004-0000", "100 Test Ave", "Residential Lot", "Available")
            + tr("30-07-15-221-005-0000", "101 Test Ave", "Residential Lot", "Pending")
            + tr("30-07-15-221-006-0000", "102 Test Ave", "House", "Available")
            + tr("30-07-15-221-007-0000", "103 Test Ave Apt 4", "Residential Lot", "Available")
            + '</table><script>var markersOnMap = [{"ppn":"30-07-15-221-004-0000","LatLng":{"lat":41.5,"lng":-88.1}}];</script>'
        )
        rows = adapters.parse_south_suburban(page)
        self.assertEqual([(x["apn"], x["price"], x["lat"], x["status"]) for x in rows],
                         [("30-07-15-221-004-0000", None, 41.5, "listed")])

    def test_newburgh_is_scoped_to_the_current_sale_section(self):
        rows = adapters.parse_newburgh_sale(
            '<h2>Currently Available for Sale:</h2><p><a>10-2-29</a> | 302 Test St (vacant lot)</p>'
            '<p>10-2-28 | 303 Test St (house)</p><h2>Not for sale at this time</h2>'
            '<p>10-2-30 | 304 Test St (vacant lot)</p>'
        )
        self.assertEqual([(x["apn"], x["price"], x["status"]) for x in rows], [("10-2-29", None, "listed")])

    def test_salt_lake_joins_notice_to_only_unimproved_parcels(self):
        page = (
            '<h2 id="stack">Available Parcels</h2>'
            '<div class="accordion-item rack" id="s-123"><button>1 Main St, Holladay, UT</button>'
            '<li><strong>Parcel #</strong>: 22-02-157-014-0000</li>'
            '<li><strong>Total Acreage</strong>: 0.29</li>'
            '<li><strong>Minimum Price</strong>: $385,000<br><strong style="font-size: 1rem;">'
            'Offer Close Date</strong>: April 30, 2027</li>'
        )
        notices = list(adapters.parse_salt_lake_notices(page))
        assessor = {"parcel_id": "22021570140000", "full_mkt_total_bldg": 0, "adjusted_total_bldg": 0,
                    "total_sq_ft": 0, "num_housing_units": 0}
        rows = adapters.parse_salt_lake_sales(notices, [{"attributes": assessor}])
        self.assertEqual([(x["apn"], x["price"], x["offer_close_date"], x["locality"]) for x in rows],
                         [("22-02-157-014-0000", 385000, "2027-04-30", "Holladay")])
        for attributes in ({}, dict(assessor, total_sq_ft=120), dict(assessor, full_mkt_total_bldg=15000)):
            self.assertEqual(adapters.parse_salt_lake_sales(notices, [{"attributes": attributes}]), [])

    def test_muncie_requires_a_listed_vacant_lot_with_an_open_auction(self):
        page = (
            '<title>1 Test St - Muncie Land Bank</title>'
            '<script>{"name":"Vacant Lot","@id":"https://muncielandbank.org/product-category/vacant-lot/"}</script>'
            '<p>The minimum bid is $500.</p><div id="yith-wcact-form-bid"></div>'
            '<label id="dateend">December 31, 2026 12:00 AM</label><label>EST</label>'
        )
        url = "https://muncielandbank.org/product/1-test-st/"
        row = adapters.parse_muncie_lot(page, url, NOW)
        self.assertEqual((row["price"], row["status"], row["deadline"]), (500, "auction_open", "2026-12-31T05:00:00Z"))
        self.assertIsNone(adapters.parse_muncie_lot(page, url, NOW + datetime.timedelta(days=45)))
        self.assertIsNone(adapters.parse_muncie_lot(page.replace("Vacant Lot", "House"), url, NOW))

    def test_harris_matches_active_sale_cards_to_unimproved_appraisal_records(self):
        template = ('<li class="row listing"><div class="{status}-small"></div>'
                    'Account#: <strong>{pid}</strong> Minimum Bid: $<strong>2,500.10</strong></li>')
        page = '<h2>Sale Date: December 01, 2026</h2><ul class="list-listings-2">'
        page += template.format(status="For Sale", pid="0000000000001")
        page += template.format(status="Cancelled", pid="0000000000002")
        page += template.format(status="For Sale", pid="0000000000003")
        date, notices = adapters.parse_harris_notices(page + "</ul>")
        land = {"state_class": "C1", "bld_value": 0, "impr_value": 0, "acreage_1": 0.4}
        features = [{"attributes": dict(land, acct_num="0000000000001")},
                    {"attributes": dict(land, acct_num="0000000000002")},
                    {"attributes": dict(land, acct_num="0000000000003", impr_value=15000)}]
        rows = adapters.parse_harris_sale(date, notices, features)
        self.assertEqual([(r["apn"], r["price"], r["acres"], r["offer_close_date"]) for r in rows],
                         [("0000000000001", 2500.10, 0.4, "2026-12-01")])

    def test_glynn_filters_out_structures_and_properties_in_foreclosure(self):
        page = ('<main><h2>Available Properties</h2>'
                '<div><h3>1 Test St</h3><h4>$5,000</h4><p>A 0.17 acre wooded lot.</p></div>'
                '<div><h3>2 Test St</h3><h4>$6,000</h4><p>A 0.25 acre vacant lot in foreclosure.</p></div>'
                '<div><h3>3 Test St</h3><h4>$7,000</h4><p>A 0.4 acre lot with a structure.</p></div></main>')
        rows = adapters.parse_glynn_landbank(page)
        self.assertEqual([(r["address"], r["price"], r["price_kind"]) for r in rows], [("1 Test St", 5000, "application")])

    def test_king_uses_only_vacant_land_in_the_surplus_section(self):
        page = ('<h2>Tax Title Property</h2><p>Vacant Land</p><p>Parcel Number 987654-3210</p>'
                '<div><h2>Surplus Property</h2><p>Former mills</p><p>Parcel Number 111111-1111</p>'
                '<p>Vacant Land</p><p><a>Parcel Number 123456-7890</a></p>'
                '<p>312 Way SE</p><p>Near Enumclaw</p><p>$225,000</p></div>')
        self.assertEqual(adapters.parse_king_surplus(page), [("123456-7890", "312 Way SE", 225000)])

    def test_caltrans_uses_lot_location_from_the_data_sheet_only(self):
        brochure = (
            "PROPERTY LOCATION State Route 99 - Google Maps CONTACT Private Test Contact "
            "DATA SHEET DD 84998-01-01 PROPERTY Unimproved vacant lot. Access is in Madera County. "
            "LOCATION State Route 99 - Google Maps SIZE Total 22,930+/- sf. ft. "
            "MINIMUM BID $500.00 Submittal Deadline – Friday, January 15, 2027, by 3:00 PM (Pacific Standard Time)."
        )
        url = "https://dot.ca.gov/auction.pdf"
        row = adapters.parse_caltrans_brochure(brochure, url, NOW)
        self.assertEqual((row["address"], row["price"], row["deadline"], row["county"]),
                         ("State Route 99", 500, "2027-01-15T23:00:00Z", "Madera"))
        self.assertNotIn("Private Test Contact", repr(row))
        self.assertIsNone(adapters.parse_caltrans_brochure(brochure, url, NOW + datetime.timedelta(days=100)))

    def test_ma_land_for_homes_omits_houses_and_prior_auctions(self):
        page = ('<div><h3 id="upcoming-auction">Upcoming Auction</h3>'
                '<p>Parcels will be available at auction on <strong>Wednesday, December 2, 2026 at 11am</strong>.</p>'
                '<p><a href="/doc/state-land-for-homes-flyer-billerica/download">0 Test Road, Billerica</a> '
                'A vacant ±2.7-acre lot. <a href="/doc/state-land-for-homes-flyer-rowley/download">'
                '1 Test Road, Rowley</a> – An existing home on a 3-acre tract.</p></div>')
        rows = adapters.parse_ma_land_for_homes(page, NOW)
        self.assertEqual([(r["county"], r["acres"], r["price"], r["offer_close_date"]) for r in rows],
                         [("Middlesex", 2.7, None, "2026-12-02")])
        self.assertEqual(adapters.parse_ma_land_for_homes(page, NOW + datetime.timedelta(days=30)), [])

    def test_lakota_lot_numbers_and_city_rate_use_current_sale_notice(self):
        page = ('<p>All residential city lots are sold for $.25/SF and require construction.</p>'
                '<aside><h2>Hulstrand Addition</h2><p>Lots 2 &amp; 3 are for sale.</p>'
                '<img src="/plat.jpg" alt="Hulstrand Addition"></aside>')
        self.assertEqual(adapters.parse_lakota_lots(page),
                         (0.25, ["2", "3"], "https://www.lakota-nd.com/plat.jpg"))
        with self.assertRaises(adapters.StructureError):
            adapters.parse_lakota_lots(page.replace("2 &amp; 3", "7 &amp; 8"))

    def test_princeton_price_uses_each_official_tracts_area(self):
        brochure = ("Two lots available for industrial development.\n"
                    "Sale Price Per Lot: $50,000 per acre\n"
                    "PID 1:  24-687-0020 4.06 Acres\nPID 2:  24-687-0030 6.28 Acres")
        self.assertEqual(adapters.parse_princeton_industrial(brochure),
                         [("24-687-0020", 4.06, 203000), ("24-687-0030", 6.28, 314000)])

    def test_burlington_requires_a_sale_lot_and_parcel_number(self):
        page = ('<main><h2>City-Owned Lots - For Sale (Structure Required):</h2><ul>'
                '<li><a href="https://www.dmcgis.com/apps/gma?parcelid=11-31-453-034">306 Test Road</a></li>'
                '<li>Parcel: 16-06-126-003</li><li>Unknown parcel</li>'
                '<li><a href="https://www.dmcgis.com/apps/gma?parcelid=11-31-453-035">305 Test Road (pending)</a></li>'
                '</ul><h2>City-Owned Property - For Sale:</h2><ul><li>House</li></ul></main>')
        rows = adapters.parse_burlington_lots(page)
        self.assertEqual([(r["apn"], r["price"], r["address"]) for r in rows],
                         [("11-31-453-034", None, "306 Test Road"), ("16-06-126-003", None, "")])

    def test_desoto_matches_vacancy_and_uses_the_clerks_auction_time(self):
        offers = [{"parcel": f"05-39-25-0000-0180-{i:04d}", "status": status,
                   "iso_sale_date": date, "opening_bid": "1234.50", "sale_time": "12:00 am",
                   "owner": "Private Test Name"}
                  for i, status, date in [(1, "scheduled", "2026-12-09"), (2, "scheduled", "2026-12-09"),
                                          (3, "sold", "2026-12-09"), (4, "scheduled", "2026-10-07"),
                                          (5, "scheduled", "2026-12-09"), (6, "scheduled", "2026-12-09")]]
        page = ('<p>All sales start at 11:00 AM.</p><tax-deed-sales :taxdeeds="' +
                html.escape(json.dumps(offers), quote=True) + '"></tax-deed-sales>')

        class Fetch:
            def text(self, url):
                return page

            def json(self, url):
                return {"features": [{"attributes": {"PARCELNO": f"05392500000180{i:04d}",
                                                     "NO_BULDNG": buildings, "DOR_UC": use, "LND_SQFOOT": 43560}}
                                     for i, buildings, use in [(1, 0, "000"), (2, 1, "010"), (3, 0, "000"),
                                                               (4, 0, "000"), (5, 0, "002"), (6, None, "000")]]}

        rows, _ = adapters.desoto_fl_auctions(Fetch(), NOW, print)
        self.assertEqual([(row["apn"], row["price"], row["deadline"]) for row in rows],
                         [("05-39-25-0000-0180-0001", 1234.50, "2026-12-09T16:00:00Z")])
        self.assertNotIn("Private Test Name", repr(rows))

    def test_greenburgh_uses_one_starting_bid_for_a_combined_lot(self):
        page = ("Town of Greenburgh Online Only Tax Foreclosure Real Estate Auction "
                "lots.lotsById[1] = lot1; Closes: Dec 2, 2026 10:00:00 AM EST Starting Bid: $81,858.00 "
                '<a href="/servlet/Search.do?auctionId=5&amp;itemId=1">More Info / Bid</a> '
                "Residential vacant land. Combined lot. Tax Map #: 6.50-35-12 6.50-35-13 Lot Size: .41 Acres "
                "lots.lotsById[2] = lot2; Closes: Dec 2, 2026 10:02:00 AM EST Starting Bid: $164,678.00 "
                "Single family residence. Tax Map #: 6.50-35-16 Lot Size: .75 Acres")
        rows = adapters.parse_greenburgh_catalog(page, "https://aarauctions.com/servlet/Search.do?auctionId=5", NOW)
        self.assertEqual([(r["id"], r["price"], r["apn"], r["acres"], r["deadline"]) for r in rows],
                         [("ny-greenburgh-auction-1", 81858, "", 0.41, "2026-12-02T15:00:00Z")])
        self.assertEqual(rows[0]["url"], "https://aarauctions.com/servlet/Search.do?auctionId=5&itemId=1")
        self.assertIn("6.50-35-12 · 6.50-35-13", repr(rows[0]["facts"]))

    def test_rochester_omits_demolition_and_keeps_bid_estimates_in_facts(self):
        report = ("SBL Property Address Zipcode Lot Size Use Code Description Assessed Value Estimated Minimum Bid Demolition Status (Y/N)\n"
                  "091.77-5-24 00162 TEST AVE 14621 50 X 100 Residential, Vacant Land $10,000.00 $81,862.04\n"
                  "091.77-5-25 00163 TEST AVE 14621 50 X 100 Residential, Vacant Land $10,000.00 $81,862.04 Y\n"
                  "091.77-5-26 00164 TEST AVE 14621 50 X 100 Residential, Single Family $10,000.00 $81,862.04\n")
        rows = adapters.parse_rochester_environmental_pdf(report, datetime.date(2026, 12, 14), "https://www.cityofrochester.gov/test.pdf")
        self.assertEqual([(r["apn"], r["address"], r["price"], r["acres"]) for r in rows],
                         [("091.77-5-24", "162 Test Ave", None, None)])
        self.assertIn("City estimate $81,862.04", repr(rows[0]["facts"]))
        self.assertIn("contamination", repr(rows[0]["facts"]))

    def test_venango_separates_price_tiers_and_excludes_withdrawals(self):
        title = "PROPERTIES AVAILABLE FOR SALE BY THE TAX CLAIM\nBUREAU\n"
        first = "The minimum bid is $1,000.00 for these properties and $500.00 for the mobile homes.\n"
        second = "The minimum bid is $600.00 for these properties and $300.00 for the mobile homes.\n"
        vacant = " " * 73 + "2.00 ACRES VACANT LAND\n"
        report = (title + first + "Private Test Name       01,003.-005..-000      TEST ROAD\n" + vacant +
                  "*Private Test Name      01,003.-006..-000      WITHDRAWN ROAD\n" + vacant + second +
                  "Private Test Name       01,003.-007..-000      TEST STREET\n" + vacant +
                  "Private Test Name       01,003.-008..-000      OLD RAILROAD R.O.W.\n" + vacant)
        rows = adapters.parse_venango_repository(report, "https://www.venangocountypa.gov/list.pdf")
        self.assertEqual([(r["apn"], r["price"], r["acres"]) for r in rows],
                         [("01,003.-005..-000", 1000, 2.0), ("01,003.-007..-000", 600, 2.0)])
        self.assertNotIn("Private Test Name", repr(rows))

    def test_maricopa_offered_land_omits_ambiguous_duplicates_and_partial_apns(self):
        def item(apn, number):
            return (f"<tr><td>Assessor's Parcel Number: {apn} District Parcel Number: {number} "
                    "Location: Test Place Size: 1.2 acres +/- Present Use: Vacant Land Shape of Property: "
                    "Minimum Bid: To be determined Required Deposit: Listing Package</td></tr>")

        page = ("Available for Sale" + item("Portion of 401-42-269B", "TEST-01") +
                item("401-42-271", "TEST-02") + item("401-42-271", "TEST-03"))
        rows = adapters.parse_maricopa_land(page)
        self.assertEqual([(r["id"], r["price"], r["apn"]) for r in rows],
                         [("az-maricopa-excess-test-01", None, "")])

    def test_san_diego_prices_only_active_sealed_bid_lots(self):
        page = ("Assessor’s Parcel Number: 381-051-17 Size: 11.71 acres Description: Subject site is currently vacant land. "
                "The minimum bid for Property 1 is seven million dollars ($7,000,000). "
                "Sealed bids will be accepted until 4:30PM on January 15, 2027.")
        row = adapters.parse_san_diego_sale(page, "https://www.sandiegocounty.gov/test.html", NOW)
        self.assertEqual((row["apn"], row["price"], row["deadline"]), ("381-051-17", 7000000, "2027-01-16T00:30:00Z"))
        self.assertIsNone(adapters.parse_san_diego_sale(page, "https://www.sandiegocounty.gov/test.html",
                                                       NOW + datetime.timedelta(days=120)))

    def test_rawlins_reserve_is_the_offer_floor_and_not_the_lien(self):
        report = ("SP-2026-001 Bid Submission Deadline Thursday, December 3, 2026 – 2:00PM MST "
                  "Property Information Item Description Property ID 1 Legal Description Lot 1 (commonly known as "
                  "619 W. Spruce Street) Zoning C2 Approximate Area 17,160 SF / 0.39 Acres Current title is held by "
                  "the city Reserve Price $59,800.00 Abatement Lien Information $65,029.76")
        row = adapters.parse_rawlins_spruce_sale(report, "https://www.rawlinswy.gov/packet", NOW)
        self.assertEqual((row["price"], row["acres"], row["deadline"]), (59800, 0.39, "2026-12-03T21:00:00Z"))
        self.assertNotIn("65,029.76", repr(row))

    def test_multnomah_requires_current_land_classification_and_matching_bid(self):
        title = "MULTNOMAH COUNTY TAX TITLE AUCTION LIST: DECEMBER 2, 2026\n"
        report = (title + "AUCTION COMMENCES-10:00 AM\n"
                  "1 RMLS R100000 TEST ADDR 2023 $23,000 $5,000\n"
                  "2 RMLS R100001 TEST ADDR 2023 $3,100 MIN. BID Withdrawn\n"
                  "3 VERTICAL EMAIL R100002 PARKING UNIT 2023 $3,200\n"
                  "4 RMLS R100003 TEST ADDR 2023 $4,100\n"
                  "5 RMLS R100004 IMPROVED HOME 2023 $5,100\n")

        def classification(index, category, id_, price):
            # Mirror the PDF's layout columns and show acreage on the next line.
            label = f"{index}   {category:17}RMLS         {id_}"
            return f"{label:48}{'LOT 1':35}{'123 TEST ST, PORTLAND,':33}2023   ${price}\n"

        classifications = (title + f"{'    TYPE             LISTING      ACCT':48}{'LEGAL':35}{'SITUS':33}FCL\n" +
                           classification(1, "LAND", "R100000", "23,000") + " " * 48 + "0.29 ACRES\n" +
                           classification(2, "LAND", "R100001", "3,100") +
                           classification(4, "LAND", "R100003", "4,099") +
                           classification(5, "IMPROVED", "R100004", "5,100"))
        rows = adapters.parse_multnomah_auction(report, classifications, adapters.MULTNOMAH_OR_AUCTION,
                                                adapters.MULTNOMAH_OR_RESOURCES, NOW)
        self.assertEqual([(r["apn"], r["price"], r["acres"], r["deadline"]) for r in rows],
                         [("R100000", 23000, 0.29, "2026-12-02T18:00:00Z")])

    def test_connecticut_asking_price_separate_from_deposit_and_after_deadline(self):
        page = ("<h1>143-152-001A-Torrington-Item No. 858-Bid Date: Still Available</h1>"
                "<p>PUBLIC BID</p><p>State Department of Transportation</p><p>Bid Date: Still Available</p>"
                "<p><strong>Location</strong>: Test Route</p><p><strong>Lot Size</strong>: 7,935&plusmn; square feet of vacant land</p>"
                "<p><strong>Asking Price</strong>: $41,000.00</p><p>$1,000.00 administrative fee</p><p>Deposit: 10%</p>")
        row = adapters.parse_ctdot_bid(page, adapters.CTDOT_SALE, NOW)
        self.assertEqual((row["price"], row["price_kind"], row["acres"], row["county"], row["apn"]),
                         (41000, "asking", round(7935 / 43560, 6), "Northwest Hills Planning Region", ""))
        self.assertIn("$1,000.00 separate administrative fee", repr(row))
        dated = page.replace("<p>Bid Date: Still Available</p>", "<p>Bid Date: January 13, 2027 - 2:00 PM</p>")
        row = adapters.parse_ctdot_bid(dated, adapters.CTDOT_SALE, NOW, require_date=True)
        self.assertEqual(row["deadline"], "2027-01-13T19:00:00Z")
        self.assertIsNone(adapters.parse_ctdot_bid(dated, adapters.CTDOT_SALE, NOW + datetime.timedelta(days=120)))
        self.assertIsNone(adapters.parse_ctdot_bid(page.replace("vacant land", "vacant land improved with a tower"),
                                                  adapters.CTDOT_SALE, NOW))

    def test_gorham_lot_schedule_preserves_ask_and_skips_unavailable(self):
        brochure = ("Town-owned lots approximately 3 acres ready for development\nSUBDIVISION LOTS\n"
                    "Lot # Acres Buildable SF* Price\n1 15.5 AC 85,000± SF SOLD\n"
                    "2 4.5 AC 25,000± SF Under Contract\n3 6 AC 20,000± SF $425,000\n"
                    "LOT INFORMATION\n")
        rows = adapters.parse_gorham_west_lots(brochure, adapters.GORHAM_ME_BROCHURE)
        self.assertEqual([(r["id"], r["acres"], r["price"], r["price_kind"]) for r in rows],
                         [("me-gorham-cyr-3", 6, 425000, "asking")])

    def test_beltrami_otc_excludes_improved_land_and_uses_board_price(self):
        report = ("PARCELS AVAILABLE for OVER-THE-COUNTER PURCHASE\n"
                  "80.01360.00  Example Lot                City of Bemidji      Before assessments: $2,000\n"
                  "No Improvements                         Map acres: 0.08     Est. Market Value: $4,000\n"
                  "                                                            Purchase Price: $9,460.02\n"
                  "49.00109.00  Separate Site              Waskish Township    Est. Market Value: $84,900\n"
                  "House / Outbuilding                     Map acres: 4.00     Purchase Price: $84,900\n")
        rows = adapters.parse_beltrami_otc(report, adapters.BELTRAMI_MN_SALE)
        self.assertEqual([(r["apn"], r["acres"], r["price"], r["locality"]) for r in rows],
                         [("80.01360.00", 0.08, 9460.02, "Bemidji")])

    def test_altoona_requires_for_sale_vacant_land_with_no_recorded_building(self):
        item = {"Status": "For Sale", "PropertyType": "Vacant Lot", "PAR_NUM": "01.11-11..-020.00-000",
                "NEW_MV_BLD": 0, "SITUS_ADD": "1018 Test Avenue", "DEED_AC": 0.027, "SALE_PRICE": 1000,
                "PREV_OWNER": "Private Test Name"}
        offers = adapters.parse_altoona_land([{"attributes": item}, {"attributes": dict(item, Status="Pending")},
                                              {"attributes": dict(item, NEW_MV_BLD=500)}])
        self.assertEqual([(r["apn"], r["acres"], r["price"]) for r in offers], [(item["PAR_NUM"], 0.027, None)])
        self.assertNotIn("Private Test Name", repr(offers))

    def test_craven_requires_county_owned_vacancy_not_assessment_price(self):
        rows = [
            ("Craven County Property Available For Purchase 11/10/2026",),
            ("County Parcel Id", "Owner Name", "Property Address", "Acres", "Description", "City", "Land Value", "Building Value"),
            ("8-014   -184", "CRAVEN COUNTY & NEW BERN-CITY OF", "101 TEST STREET", .1, "Wooded landlocked lot", "NEW BERN", 5000, 0),
            ("8-014   -270", "CRAVEN COUNTY", "102 TEST STREET", .1, "Lot with garage", "NEW BERN", 10000, 3000),
            ("8-014   -299", "Private Test Name", "103 TEST STREET", .1, "Vacant lot", "NEW BERN", 5000, 0),
        ]
        offers = adapters.parse_craven_county_offers(rows, adapters.CRAVEN_NC_SALE)
        self.assertEqual([(r["apn"], r["acres"], r["price"]) for r in offers], [("8-014-184", .1, None)])
        self.assertEqual(offers[0]["facts"][-1]["topic"], "road_access")
        self.assertNotIn("Private Test Name", repr(offers))

    def test_mndot_requires_current_vacant_directory_and_matching_map_sale_type(self):
        otc = '<li><a href="https://example.test">Sale 139574</a> (PDF) - 17,005 Square Feet of Vacant Land located at E. Alabama Street, St. Paul, Ramsey County, MN.</li>'
        bids = ('<p>All bids must be received by 1:45 PM. on the day of the bid opening.</p>'
                '<p><a href="https://example.test">Sale 139625</a> (PDF) - 4.50 Acres of Vacant Land located at TH 10, '
                'Sauk Rapids, Benton County, MN. <strong>*Bid Opening December 2, 2026</strong></p>')
        features = [{"attributes": {"SaleNumber": "Sale 139574", "SaleType": "Over-the-counter", "Price": "$68,000.00"}},
                    {"attributes": {"SaleNumber": "Sale 139625", "SaleType": "Sale by bid", "Price": "$31,500.00"}},
                    {"attributes": {"SaleNumber": "Sale 139699", "SaleType": "Sale by bid", "Price": "$10,000.00"}}]
        directories = {adapters.MNDOT_SALE: bids, adapters.MNDOT_OTC: otc}
        close = datetime.datetime(2026, 12, 2, 19, 45, tzinfo=datetime.timezone.utc)
        rows = adapters.parse_mndot_offers(directories, features, close - datetime.timedelta(minutes=1))
        self.assertEqual([(r["id"], r["price"], r["price_kind"], r["deadline"]) for r in rows],
                         [("mn-mndot-139625", 31500, "asking", "2026-12-02T19:45:00Z"), ("mn-mndot-139574", 68000, "cash", None)])
        self.assertEqual(len(adapters.parse_mndot_offers(directories, features, close)), 1)


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

    def test_van_buren_uses_only_exact_positive_vacant_assessments_for_area(self):
        sale = dict(self.ROW, CoSLCountyName="VAN BUREN", CoSLParcelNumber="4050-05055-0000")
        land = adapters.arkansas_listing(sale, NOW)
        improved = adapters.arkansas_listing(dict(sale, CoSLParcelNumber="4050-05053-0000"), NOW)
        uncertain = adapters.arkansas_listing(dict(sale, CoSLParcelNumber="4050-05054-0000"), NOW)
        attrs = {"County": "Van Buren", "CountyFips": 5141, "ParcelType": "RV", "LandValue": 2000,
                 "TotalValue": 2000, "ImpValue": 0, "CAMADate": 1756339200000, "AdrCity": "FAIRFIELD BAY",
                 "OwnerName": "TEST PRIVATE"}
        rings = [[[-92.3, 35.6], [-92.299, 35.6], [-92.299, 35.601], [-92.3, 35.601], [-92.3, 35.6]]]
        features = [
            {"attributes": {**attrs, "ParcelId": land["apn"]}, "geometry": {"rings": rings}},
            {"attributes": {**attrs, "ParcelId": improved["apn"], "ImpValue": 50}, "geometry": {"rings": rings}},
            {"attributes": {**attrs, "ParcelId": uncertain["apn"], "ImpValue": None}, "geometry": {"rings": rings}},
        ]
        with patch.object(adapters, "arcgis_query", return_value=("https://example.test", features)) as query:
            adapters.enrich_arkansas_van_buren(unittest.mock.Mock(), [land, improved, uncertain])
        self.assertNotIn("OwnerName", query.call_args.args[3])
        self.assertNotIn("PRIVATE", repr(land))
        self.assertEqual(land["acres"], adapters.rings_acres(rings))
        self.assertEqual(land["price"], float(self.ROW["StartingBid"]))
        self.assertEqual(land["locality"], "Fairfield Bay")
        for row in (improved, uncertain):
            self.assertIsNone(row["acres"])
            self.assertIn("improvements unverified", row["tags"])


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


class DetroitAndKcAndCaTest(unittest.TestCase):
    def test_detroit_filters_marketed_lots(self):
        feats = [
            {"attributes": {"parcel_id": "17013507.", "name": "698 Field", "inventory_status_socrata": "Marketed Lot For Sale",
                            "neighborhood": "Islandview", "council_district": 5, "latitude": 42.3506, "longitude": -83.0018}},
            {"attributes": {"parcel_id": "99999999.", "name": "100 Other", "inventory_status_socrata": "DLBA Owned Structure",
                            "latitude": 42.35, "longitude": -83.0}},
        ]
        rows = adapters.parse_detroit_features(feats, lambda w: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["state"], rows[0]["county"], rows[0]["price_kind"]), ("MI", "Wayne", "none"))
        self.assertTrue(rows[0]["url"].startswith("https://buildingdetroit.org/"))

    def test_detroit_acreage_requires_an_exact_unimproved_assessor_match(self):
        def assessment(parcel_id, acreage, improved):
            return {"attributes": {"parcel_id": parcel_id, "total_acreage": acreage, "is_improved": improved}}

        class Assessor:
            def json(self, url, *, form):
                self.query = form
                return {"features": [assessment("01001587.", 0.157, 0), assessment("01001588.", 0.138, 1),
                                     assessment("01001689.004", 0.022, 0), assessment("01001689.004", 0.026, 0),
                                     assessment("01001689.005", 0.4, 0)]}

        fetch = Assessor()
        rows = [{"apn": parcel_id, "acres": None, "facts": []}
                for parcel_id in ("01001587", "01001588", "01001689.004", "01001689.001")]
        adapters.enrich_detroit_assessor_acreage(fetch, rows)
        self.assertEqual([row["acres"] for row in rows], [0.157, None, None, None])
        self.assertEqual(rows[0]["facts"][0]["url"], "@detroit_assessor")
        self.assertIn("'01001587.'", fetch.query["where"])
        self.assertEqual(fetch.query["outFields"], "parcel_id,total_acreage,is_improved")
        self.assertEqual(fetch.query["returnGeometry"], "false")

    def test_kc_filters_acquired_vacant_land_bank_and_keeps_zoning(self):
        raw = [
            {"parcel_number": "JA28810112600000000", "property_class": "Residential Vacant", "property_status": "Acquired",
             "inventory_type": "Land Bank", "zoned_as": "R-2.5", "address": "5608 E 28th St", "county": "JACKSON",
             "square_footage": "8985.61", "location_1": {"latitude": "39.07454", "longitude": "-94.51766"}},
            {"parcel_number": "JA999", "property_class": "Residential Vacant", "property_status": "Disposed",
             "inventory_type": "Land Bank", "address": "1 Old St"},
        ]
        rows = adapters.parse_kc_rows(raw, lambda w: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["state"], rows[0]["county"], rows[0]["price"]), ("MO", "Jackson", None))
        self.assertTrue(any(f["topic"] == "zoning" and f["value"] == "R-2.5" for f in rows[0]["facts"]))

    def test_california_dgs_parses_deadlines(self):
        html_doc = "<ul><li>CDCR Norco, Fifth Street, Site ID #S065202 - Proposal Deadline November 30, 2026</li></ul>"
        rows = adapters.parse_california_dgs(html_doc, NOW, lambda w: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["state"], rows[0]["county"], rows[0]["status"]), ("CA", "Riverside", "proposal_open"))
        self.assertTrue(rows[0]["deadline"].startswith("2026-12-01"))


class Phase2AdaptersTest(unittest.TestCase):
    RING = [[[-85.76, 38.24], [-85.76, 38.2403], [-85.7595, 38.2403], [-85.7595, 38.24], [-85.76, 38.24]]]

    def test_chicago_apply_and_offered(self):
        raw = [
            {"id": "70039", "pin": "13-35-311-049-0000", "address": "3745 W CORTLAND ST",
             "property_status": "Owned by City", "sales_status": "Apply", "zoning_classification": "PD 1540",
             "square_footage_city_estimate": "4356", "application_deadline": "2027-01-15T00:00:00.000",
             "application_url": {"url": "https://www.chicago.gov/city/en/sites/block-builder/home/public-notice.html"},
             "latitude": "41.915", "longitude": "-87.721", "land_value": "25000"},
            {"id": "1", "pin": "99", "address": "1 CLOSED ST", "property_status": "Owned by City", "sales_status": "Application Closed"},
        ]
        rows = adapters.parse_chicago_rows(raw, NOW, lambda w: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["state"], rows[0]["status"], rows[0]["price"]), ("IL", "proposal_open", None))
        self.assertTrue(rows[0]["deadline"].startswith("2027-01-16"))
        self.assertAlmostEqual(rows[0]["acres"], 0.1, places=3)

    def test_pittsburgh_vacant_public_sale_only(self):
        raw = [
            {"id": "176879", "pin": "0075B00072000000", "address": "3556 ELMHURST AVE", "parc_sq_ft": 32450,
             "class": "Vacant Land", "zoned_as": "H", "inventory_type": "Public Sale", "current_status": "Available for Sale",
             "latitude": 40.4807, "longitude": -80.044, "neighborhood_name": "Brighton Heights"},
            {"id": "2", "pin": "0001", "address": "1 PARK AVE", "class": "Vacant Land", "inventory_type": "Park", "current_status": "Available for Sale"},
        ]
        rows = adapters.parse_pittsburgh_rows(raw, lambda w: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["state"], rows[0]["county"], rows[0]["price_kind"]), ("PA", "Allegheny", "none"))
        self.assertTrue(rows[0]["url"].startswith("https://pghlandbank.org"))

    def test_louisville_and_lucas_and_la_and_broward_and_udot(self):
        lou = adapters.parse_louisville_features([{
            "attributes": {"Parcel_No_": "040J00710000", "Street_Add": "2315 WOODLAND AVE", "Property_S": "Available",
                           "Inventory_": "Lot", "Buildable_": "Yes", "Council_Di": 6},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual(len(lou), 1)
        self.assertEqual((lou[0]["state"], lou[0]["county"]), ("KY", "Jefferson"))
        self.assertIsNotNone(lou[0]["geometry"])

        lucas = adapters.parse_lucas_features([{
            "attributes": {"parid": "1543874", "property_address": "515 MULBERRY ST, TOLEDO OH 43604",
                           "luc": "640", "zoning": "10-RD6", "acreage_calc": 0.095, "owner": "SECRET PERSON"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual(len(lucas), 1)
        self.assertNotIn("SECRET", repr(lucas[0]))
        self.assertEqual((lucas[0]["state"], lucas[0]["county"]), ("OH", "Lucas"))

        la = adapters.parse_la_ttc_features([{
            "attributes": {"APN": "3244-092-033", "TaxRateCit": "SANTA CLARITA", "UseType": "Irrigated Farm",
                           "AUC_ITEM": 2768, "AUC_MINBID": 15896, "AUC_ADDR": "VACANT LOT", "Owner": "PRIVATE NAME"},
            "geometry": {"rings": self.RING},
        }], "2026B", lambda w: None)
        self.assertEqual(len(la), 1)
        self.assertNotIn("PRIVATE NAME", repr(la[0]))
        self.assertEqual((la[0]["state"], la[0]["price"], la[0]["price_kind"]), ("CA", 15896.0, "min_bid"))

        fl = adapters.parse_broward_features([{
            "attributes": {"FOLIO": "504011010600", "LEGAL_LINE_1": "FLA FRUIT LANDS", "USE_CODE": "94"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual(len(fl), 1)
        self.assertEqual((fl[0]["state"], fl[0]["county"]), ("FL", "Broward"))
        self.assertIn("bcpa.net", fl[0]["url"])

        ut = adapters.parse_udot_features([{
            "attributes": {"parcel_number": "173:T", "tax_id": "09-085-0036", "county": "WEBER", "city": "ROY",
                           "situs_address": "3029 West 5600 South", "sell_entry_number": None, "void_date": None, "acreage_epm": 11358},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual(len(ut), 1)
        self.assertEqual((ut[0]["state"], ut[0]["county"]), ("UT", "Weber"))

    def test_phase3_ny_fl_nm_md_tx(self):
        ny = adapters.parse_albany_features([{
            "attributes": {"PIN_SBL": "08702300010040000000", "print_key": "87.23-1-4", "full_addre": "187A MOUNT HOPE DR",
                           "prop_class": "311", "class_desc": "Residential Vacant Land", "acres": 0.069, "rezone1": "R-T"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ny), ny[0]["state"], ny[0]["county"]), (1, "NY", "Albany"))

        ora = adapters.parse_orange_fl_features([{
            "attributes": {"USER_TDA_NUM": "2024-12942", "USER_Sale_Date": "01/07/2027",
                           "USER_Deed_Status": "Active Sale", "USER_PARCEL": "10-24-29-3055-17-060"},
            "geometry": {"x": -81.408, "y": 28.409},
        }], NOW, lambda w: None)
        self.assertEqual((len(ora), ora[0]["state"], ora[0]["status"]), (1, "FL", "auction_open"))
        self.assertTrue(ora[0]["deadline"].startswith("2027-01-07"))

        nm = adapters.parse_lascruces_features([{
            "attributes": {"ACCOUNTNUM": "R0219246", "TOTALACRES": 2.34, "CouncilDistrict": 6},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(nm), nm[0]["state"]), (1, "NM"))

        md = adapters.parse_baltimore_features([{
            "attributes": {"PIN": "0563043", "BLOCKLOT": "0563 043", "ZONECODE": "C-5HS", "LOT_SIZE": "85X92-1"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(md), md[0]["state"], md[0]["county"]), (1, "MD", "Baltimore City"))

        tx = adapters.parse_bigspring_features([{
            "attributes": {"prop_id_te": "49828", "legal_acre": 0.2, "legal_desc": "SE/4 OF SC 32", "situs_num": "310", "situs_stre": "NOLAN"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(tx), tx[0]["state"], tx[0]["county"]), (1, "TX", "Howard"))

    def test_phase4_wa_nc_ga_co_az_la_nj_fl(self):
        wa = adapters.parse_king_wa_features([{
            "attributes": {"PIN": "0000200038", "CAT_TYPE": "Tax Title", "ACREAGE": 0.46, "JURISDICTIONATACQUISITION": "KENT"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(wa), wa[0]["state"], wa[0]["status"]), (1, "WA", "auction_terms"))

        nc = adapters.parse_charlotte_features([{
            "attributes": {"ParcelID": "00155107", "Address": "22928 Torrance Chapel Rd.", "Acres": 4.65, "LandImprovements": "Undeveloped"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(nc), nc[0]["state"]), (1, "NC"))

        ga = adapters.parse_canton_ga_features([{
            "attributes": {"PIN": "14-0160-0021", "Acreage": 0.36, "Zoning": "CITY"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ga), ga[0]["state"]), (1, "GA"))

        co = adapters.parse_sanmiguel_co_features([{
            "attributes": {"PIN": "452335316008", "LOC_CITY": "PLACERVILLE", "LEGAL_DESC": "LOTS 4 5 AND 6"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(co), co[0]["state"]), (1, "CO"))

        az = adapters.parse_navajo_az_features([{
            "attributes": {"APN": "104-02-059A", "AuctionURL": "https://publicsurplus.com/sms/navajocounty,az/auction/view?auc=3926102"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(az), az[0]["state"], az[0]["offering"]), (1, "AZ", "auction"))

        la = adapters.parse_ebr_la_rows([{
            "assessment_num": "008-3340-1", "physadd": "9137 RIDGE OAK DR", "tax_roll_year": "2023",
            "geolocation": {"latitude": "30.354", "longitude": "-91.116"},
        }], lambda w: None)
        self.assertEqual((len(la), la[0]["state"]), (1, "LA"))

        nj = adapters.parse_cherryhill_nj_features([{
            "attributes": {"UNIQUEID": "0409-1", "BLOCK": "369.01", "LOT": "16", "HADD": "GRANT AVE"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(nj), nj[0]["state"]), (1, "NJ"))

        orl = adapters.parse_orlando_fl_rows([{
            "parcel": "03-23-29-0180-02-240", "address": "601 18th Street", "lot_size_acres": "0.15",
            "zoning": "R-1", "conforming_lot_58_1152": True, "geocoded_column": {"coordinates": [-81.386, 28.522]},
        }], lambda w: None)
        self.assertEqual((len(orl), orl[0]["state"]), (1, "FL"))

    def test_phase5_13_new_states(self):
        in_r = adapters.parse_delaware_in_features([{
            "attributes": {"State_PIN": "18-11-03-483-005", "Property_Street": "1617 E WEBER DR", "Property_City": "MUNCIE", "Minimum_Bid": 450.5, "AV___Total_Improvements": 0},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(in_r), in_r[0]["state"], in_r[0]["price_kind"]), (1, "IN", "min_bid"))

        mn1 = adapters.parse_millelacs_mn_features([{
            "attributes": {"PID": "09-965-0350", "SALEABLE": "Yes", "STRUCTURES": "No", "POLITICAL_SUBDIVISION": "Kathio Township", "ACRES": 0.52, "WATERFRONT": "Yes"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(mn1), mn1[0]["state"]), (1, "MN"))

        mn2 = adapters.parse_ottertail_mn_features([{
            "attributes": {"PIN": "67000990149000", "ACRES": 0.21, "PHYSADDR": "212 MAIN AVE E", "PHYSCITY": "DEER CREEK"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(mn2), mn2[0]["state"]), (1, "MN"))

        va = adapters.parse_richmond_va_features([{
            "attributes": {"PIN": "C0090800030", "DwellingValue": 0, "LandSqFt": 8712, "LandUse": "Vacant"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(va), va[0]["state"]), (1, "VA"))

        al = adapters.parse_montgomery_al_features([{
            "attributes": {"DISPLAY": "YES", "PARCEL_NUM": "0409321019008000", "CALC_ACRE": 0.21, "STREET_NAM": "HOUSER ST"},
            "geometry": {"x": -86.3, "y": 32.36},
        }], lambda w: None)
        self.assertEqual((len(al), al[0]["state"]), (1, "AL"))

        ia = adapters.parse_waterloo_ia_features([{
            "attributes": {"OBJECTID": 2, "Area": "75.05 Acres", "Zoning": "M-2", "TIFDistrict": "NE Industrial"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ia), ia[0]["state"], ia[0]["acres"]), (1, "IA", 75.05))

        ks1 = adapters.parse_wyandotte_ks_features([{
            "attributes": {"PARCEL": "115534", "VACANT": "Y", "ACRE": 0.15, "NUMB": "3048", "ST_NAME": "MAIN", "CITY": "KANSAS CITY"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ks1), ks1[0]["state"]), (1, "KS"))

        ks2 = adapters.parse_shawnee_ks_features([{
            "attributes": {"PIN": "1492901006022000", "PADDRESS": "4649 SW SHENANDOAH CT", "ACRES": 0.35, "BLDGVAL": 0, "SALE_PRICE": 26342},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ks2), ks2[0]["state"], ks2[0]["price_kind"], ks2[0]["price"]), (1, "KS", "cash", 26342.0))

        de = adapters.parse_wilmington_de_features([{
            "attributes": {"L0NCC_REST_Parcel_Data_PRCLID": "2602220081", "L0NCC_REST_Parcel_Data_LOTSZ": 0.03, "L0NCC_REST_Parcel_Data_ADDRESS": "105 W 29TH ST"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(de), de[0]["state"]), (1, "DE"))

        ct = adapters.parse_hartford_ct_features([{
            "attributes": {"PARCEL_ID": "159484050", "Address": "42 Francis Ave.", "LAND_USE": "Vacant Lot", "ZONE": "CX-2", "LOT_SIZE___SQ__FT__": "5500"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ct), ct[0]["state"]), (1, "CT"))

        ne = adapters.parse_omaha_ne_features([{
            "attributes": {"PIN": "0125630000", "PROPERTY_A": "6161 S 132 ST", "ACRES": 0.45, "NUMBLDGS": 0, "IMPROVEMEN": 0},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ne), ne[0]["state"]), (1, "NE"))

        wv = adapters.parse_bluefield_wv_features([{
            "attributes": {"GISPID": "28-03-0006-0004-0000", "Acres_C": 0.34, "Zone": "R-2", "FullPhysic": "100 MAIN ST"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(wv), wv[0]["state"]), (1, "WV"))

        tn = adapters.parse_memphis_tn_features([{
            "attributes": {"PARID": "03201200010", "PAR_ADDR1": "0 LUCAS ST", "LANDUSE": "VACANT", "Acres": 0.4, "CurrentZon": "EMP"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(tn), tn[0]["state"]), (1, "TN"))

        ri = adapters.parse_warwick_ri_features([{
            "attributes": {"MSPARCELID": "331-0201", "MSLOCATION": "ROANOKE AVE", "MSAREACAC": 0.13, "MSLANDUSED": "Vac Res Land"},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ri), ri[0]["state"]), (1, "RI"))

        ma = adapters.parse_boston_ma_features([{
            "attributes": {"Parcel": "0107071000", "Address": "100 MAIN ST", "Care_and_Custody": "MOH", "Lot_Size_SF": 4946},
            "geometry": {"rings": self.RING},
        }], lambda w: None)
        self.assertEqual((len(ma), ma[0]["state"]), (1, "MA"))

    def test_phase6_final_14_states_all_50(self):
        wy = adapters.parse_albany_wy_features([{"attributes": {"pidn": "20760610002700", "grossacres": 31.69, "landval": 79550, "totalval": 79550, "accttype": "Res Vacant Land"}, "geometry": {"rings": self.RING}}], lambda w: None)
        ok = adapters.parse_odot_ok_features([{"attributes": {"OBJECTID_1": 1, "Name": "F-410", "Parcel": 27, "County": "MUSKOGEE", "Acres_Remaining": 4.74}, "geometry": {"rings": self.RING}}], lambda w: None)
        ms = adapters.parse_ms_surplus_features([{"attributes": {"DPIN": "006110000329", "acres_gis": 0.24, "tv_imp": " ", "loc_num": "193", "loc_alpha": "CRESTON AVE"}, "geometry": {"rings": self.RING}}], lambda w: None)
        sc = adapters.parse_horry_sc_features([
            {"attributes": {"PIN_1": "44314040003", "Item_Number": "321"}, "geometry": {"rings": self.RING}},
            {"attributes": {"PIN_1": "44314040004", "Item_Number": "322"}},
            {"attributes": {"PIN_1": "44314040005", "Item_Number": "323"}},
        ], {"44314040003": ("321", 14691.11), "44314040004": ("322", 500), "44314040005": ("999", 100)}, {
            "44314040003": {"PARCELTYPE": 2, "MarketImprv": 0, "Acreage": 0.25},
            "44314040004": {"PARCELTYPE": 2, "MarketImprv": 200, "Acreage": 0.5},
            "44314040005": {"PARCELTYPE": 2, "MarketImprv": 0, "Acreage": 1},
        }, NOW + datetime.timedelta(days=4), adapters.HORRY_SC_URL, adapters.HORRY_SC_URL)
        self.assertEqual([(row["apn"], row["price"], row["acres"]) for row in sc], [("44314040003", 14691.11, 0.25)])
        or_r = adapters.parse_portland_or_features([{"attributes": {"STATE_ID": "11E25BA23600", "SITEADDR": "123 MAIN ST", "BLDGSQFT": 0, "A_T_ACRES": 0.25}, "geometry": {"rings": self.RING}}], lambda w: None)
        hi = adapters.parse_maui_hi_features([{"attributes": {"TMK_txt": "246007003", "BldgValue": 0, "TaxAcres": 0.43, "Jurisdiction": "Maui County"}, "geometry": {"rings": self.RING}}], lambda w: None)
        nv = adapters.parse_lasvegas_nv_features([{"attributes": {"PARCEL": "13805501015", "LOCATION": "RED COACH & DURANGO", "IMPROVEMENTNAME": "VACANT SITE", "LAT": 36.245, "LONG": -115.279}, "geometry": {}}], lambda w: None)
        nh = adapters.parse_peterborough_nh_features([{"attributes": {"PIN": "R011-041-000", "CLASSIFY": "Tax", "LOCATION": "Off Scott Mitchell", "ACREAGE": 22.34}, "geometry": {"rings": self.RING}}], lambda w: None)
        sd = adapters.parse_yankton_sd_features([{"attributes": {"PARCEL_ID": "78.790.033.250", "Location": "MAIN ST", "LEGALS": "LTS 12 BLK 33"}, "geometry": {"rings": self.RING}}], lambda w: None)
        nd = adapters.parse_burleigh_nd_features([{"attributes": {"PID": "38-138-80-60-01-013", "Acres": "0.19", "Legal": "MEADOW VIEW BLK 1", "Commercial_Building_Market": 0, "Residential_Building_Market": 0}, "geometry": {"rings": self.RING}}], lambda w: None)
        vt = adapters.parse_vcgi_vt_features([{"attributes": {"SPAN": "033-010-11098", "TOWN": "BARNET", "E911ADDR": "259 CHURCH ST", "DESCPROP": "VACANT LOT", "ACRESGL": 0.59, "IMPRV_LV": 0}, "geometry": {"rings": self.RING}}], lambda w: None)
        mt = adapters.parse_montana_cad_features([{"attributes": {"PARCELID": "36236214102010000", "CountyName": "Judith Basin", "GISAcres": 319.3, "TotalBuildingValue": 0}, "geometry": {"rings": self.RING}}], lambda w: None)
        id_r = adapters.parse_boise_id_features([{"attributes": {"PARCEL": "R0096000100", "DEPT": "COMDEV", "ACRES": 0.25, "PROPADDNUM": "100", "PROPSTNM": "MAIN", "PROPSTTYPE": "ST"}, "geometry": {"rings": self.RING}}], lambda w: None)
        me1 = adapters.parse_auburn_me_features([{"attributes": {"ParcelID": "135-100", "Address": "355 Old Danville Rd", "LandUse": "UNDEVELOPED", "Acreage": 0.34, "BldgValue": 0}, "geometry": {"rings": self.RING}}], lambda w: None)
        me2 = adapters.parse_portland_me_features([{"attributes": {"OBJECTID": 1, "Parcel_ID": "001 A001001", "Land_Use": "LAND BANKS"}, "geometry": {"rings": self.RING}}], lambda w: None)
        states = [x[0]["state"] for x in (wy, ok, ms, sc, or_r, hi, nv, nh, sd, nd, vt, mt, id_r, me1, me2)]
        self.assertEqual(states, ["WY", "OK", "MS", "SC", "OR", "HI", "NV", "NH", "SD", "ND", "VT", "MT", "ID", "ME", "ME"])
        self.assertEqual(sc[0]["price_kind"], "min_bid")
        self.assertEqual(len({s["state"] for s in adapters.SOURCES}), 50)


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


class SaukTest(unittest.TestCase):
    def test_uses_only_parcel_situs_and_geometry(self):
        rows = adapters.parse_sauk_wi_features([
            {"attributes": {"PARCELID": "101", "PSTLADDRESS": "Mailing address"}},
            {"attributes": {"PARCELID": "102", "SITEADDRESS": "P.O. Box 18"}},
            {"attributes": {"PARCELID": "103", "SITEADDRESS": "1 COUNTY ROAD"}},
        ], lambda message: None)
        self.assertEqual([row["address"] for row in rows], ["", "", "1 County Road"])
        self.assertTrue(all(row["lat"] is None and row["lon"] is None for row in rows))
        self.assertNotIn("Mailing address", repr(rows))


class CurrentOfferingsTest(unittest.TestCase):
    def test_detroit_neighborhood_price_is_published_program_price(self):
        price = adapters.parse_detroit_neighborhood_price(
            "<p>Neighborhood Lots will be sold for $250 and require a Neighborhood Lot Endorsement.</p>")
        rows = adapters.parse_detroit_features([
            {"attributes": {"parcel_id": "012", "name": "Vacant lot",
                            "inventory_status_socrata": "Neighborhood Lot For Sale"}},
            {"attributes": {"parcel_id": "013", "name": "Held lot",
                            "inventory_status_socrata": "DLBA Owned Lot"}},
            {"attributes": {"parcel_id": "014", "name": "House",
                            "inventory_status_socrata": "Marketed Structure For Sale"}},
        ], lambda message: None, price)
        self.assertEqual([(r["id"], r["price_kind"], r["price"]) for r in rows],
                         [("mi-dlba-012", "application", 250)])
        self.assertEqual(rows[0]["url"], adapters.DLBA_NEIGHBORHOOD_URL)
        self.assertIsNone(adapters.parse_detroit_neighborhood_price("The program sets terms."))

    def test_hoke_reads_open_land_and_excludes_closed_bids(self):
        table = """
        <table>
        <tr><th>Posted</th><th>Parcel Number</th><th>Approximate Acreage</th><th>Location</th>
        <th>Minimum Bid</th><th>Current Bid Amount</th><th>Upset Period Ends</th></tr>
        <tr><td>11/26</td><td>12345-01-01-020</td><td>0.25</td><td>Oak Rd</td>
        <td>$3,455.10</td><td></td><td></td></tr>
        <tr><td>10/26</td><td>12345-01-01-021</td><td>0.9</td><td>Ash Rd</td>
        <td>$2,001</td><td></td><td>CLOSED</td></tr>
        </table>
        """
        rows = adapters.parse_hoke_surplus(table, NOW, lambda message: None)
        self.assertEqual([(r["apn"], r["acres"], r["price"]) for r in rows],
                         [("12345-01-01-020", .25, 3455.10)])

    def test_wsdot_uses_county_sale_index_and_excludes_improved_properties(self):
        index = ('<h3>Properties available on a first come, first serve basis</h3>'
                 '<h3>Pierce County</h3><p><a href="/node/6338">Parcel number: 3-27-15722</a></p><h2>Terms</h2>')
        [(county, reference, url)] = adapters.parse_wsdot_index(index)
        page = ('<h2>Minimum bid</h2><p>$350,000.00</p>'
                '<h2>Location and size</h2><p>The subject is a 2.85 +/- acre parcel.</p>'
                '<h2>Improvements</h2><p>None</p><h2>Terms</h2>')
        row = adapters.parse_wsdot_property(page, county, reference, url)
        self.assertEqual((row["county"], row["price"], row["acres"]), ("Pierce", 350000, 2.85))
        small = adapters.parse_wsdot_property(page.replace("2.85 +/- acre", ".079+/- acre"), county, reference, url)
        self.assertAlmostEqual(small["acres"], 0.079)
        med = adapters.parse_wsdot_property(page.replace("2.85 +/- acre", ".69 +/- acre"), county, reference, url)
        self.assertAlmostEqual(med["acres"], 0.69)
        self.assertIsNone(adapters.parse_wsdot_property(page.replace(">None<", ">House<"), county, reference, url))

    def test_itasca_uses_unimproved_section_and_preserves_parcel_prices(self):
        report = """2026 - ITASCA COUNTY TAX-FORFEITED PROPERTY : AVAILABLE OVER-THE-COUNTER
           IMPROVED
           3#   2.0   01-002-0034   Improved property  $55,000.00
           UNIMPROVED
           1#   0.08    05-445-0930   SITE DESCRIPTION      10-55-26       $5,443.00
                0.03    74-420-0710   SITE DESCRIPTION       2-144-26        $165.00
Tracts are available for purchase at not less than the appraised price.
"""
        rows = adapters.parse_itasca_otc(report, adapters.ITASCA_URL, NOW, lambda message: None)
        self.assertEqual([(r["apn"], r["acres"], r["price"]) for r in rows],
                         [("05-445-0930", .08, 5443), ("74-420-0710", .03, 165)])


    def test_philadelphia_only_carries_lots_matching_the_sale_map(self):
        features = [
            {"attributes": {"opa_id": "341032950", "address": "6214 VINE ST"}},
            {"attributes": {"opa_id": "341032951", "address": "6260 VINE ST"}},
        ]
        rows = adapters.parse_philly_lb_features(features, {"341032950": "Owned - Available"}, lambda message: None)
        self.assertEqual([r["apn"] for r in rows], ["341032950"])
        self.assertEqual(rows[0]["url"], adapters.PHILLY_LB_URL)

class RegionalVacantOffersTest(unittest.TestCase):
    def test_salem_requires_exact_sale_and_excludes_grouped_property(self):
        page = """<h2>West Broadway Commercial Redevelopment Package</h2>
        <p>The following properties must be purchased and redeveloped together:</p>
        <p>Block/Lot: 13/46</p><h3>Former Salem Café</h3>"""
        report = """Block  Lot  Address  Notes
13   46   142-144 W Broadway
14   9    198 Pledger St  Residential
14   10   200 Pledger St  Pending
77   23   Oak St Rear     Historic area: HPC approval required
"""
        self.assertEqual(adapters.salem_nj_roster(page, report), {
            "1713_14_9": "Residential", "1713_77_23": "Historic area: HPC approval required",
        })

    def test_deldot_uses_notice_minimum_and_expires_at_auction_start(self):
        report = """Date and Time: Tuesday, December 8, 2026, 11:00 a.m. to 12:00 pm
        Kent County Tax Parcel No.: 7-02-103.00-01-     10.01-000
        Size: 0.2256 acres +/-
        Approved Appraised Value: $85,000.00
        Minimum Sale Price: $72,250.00 (85% of Approved Appraised Value)"""
        url = adapters.DELDOT_AUCTIONS
        row = adapters.parse_deldot_k303(report, url, "518 Lochmeath Way, Camden-Wyoming", NOW)
        self.assertEqual((row["apn"], row["acres"], row["price"], row["deadline"]),
                         ("7-02-103.00-01-10.01-000", .2256, 72250, "2026-12-08T16:00:00Z"))
        closed = datetime.datetime(2026, 12, 8, 16, 0, tzinfo=datetime.timezone.utc)
        self.assertIsNone(adapters.parse_deldot_k303(report, url, row["address"], closed))

    def test_conrad_checks_current_plat_and_only_uses_available_lots(self):
        class CityPage:
            def text(self, url):
                return ('<a href="https://www.cityofconrad.com/_files/ugd/other.pdf">Policy Manual</a>'
                        '<p>View the Industrial Park lots available for sale.</p>'
                        '<a href="https://www.cityofconrad.com/_files/ugd/map.pdf">Industrial Park lots</a>')

            def bytes(self, url):
                if not url.endswith("/map.pdf"):
                    raise AssertionError("wrong plat linked")
                return b"reviewed map fixture"

        with self.assertRaises(adapters.StructureError):
            adapters.conrad_mt_industrial_park(CityPage(), NOW, None)
        digest = adapters.hashlib.sha256(b"reviewed map fixture").hexdigest()
        rings = [[[-111.8, 48.1], [-111.799, 48.1], [-111.8, 48.101], [-111.8, 48.1]]]
        features = [{"attributes": {"PARCELID": pin, "TotalAcres": acres, "TotalBuildingValue": 0,
                                    "Subdivision": "CONRAD EAST INDUSTRIAL PARK SUBDIVISION"},
                     "geometry": {"rings": rings}}
                    for pin, acres in [("26398713201100000", 3.02), ("26398713201120000", 5.64), ("26398713201150000", 5.83),
                                       ("26398713201160000", 5.72)]]
        with patch.object(adapters, "CONRAD_MT_PLAT_SHA256", digest), patch.object(adapters, "_arcgis_query", return_value=features):
            rows, info = adapters.conrad_mt_industrial_park(CityPage(), NOW, None)
        self.assertTrue(info["complete"])
        self.assertEqual([(r["facts"][1]["value"], r["price"]) for r in rows], [
            ("Lot 1 of Conrad East Industrial Park Subdivision", 90600),
            ("Lot 3 of Conrad East Industrial Park Subdivision", 197400),
            ("Lot 6 of Conrad East Industrial Park Subdivision", 233200),
        ])

    def test_northumberland_requires_express_vacancy_and_uses_sealed_bid_floor(self):
        report = """Available for “SEALED BID” ONLY
MINIMUM BID $100.00
00F-01-00F-033
Maple Avenue
VAC/ LOT 12.5 X 80 FT
PRIVATE PERSON
016-01-008-039
216 E. Cameron Street
LOT 14 X 50
026-00-012-078-C-001-L
1804 Old State Road
LEASED LAND - MOBILE HOME ONLY"""
        rows = adapters.parse_northumberland_pa_repo(report, adapters.NORTHUMBERLAND_PA_REPO)
        self.assertEqual([(r["apn"], r["price"], r["acres"]) for r in rows], [("00F-01-00F-033", 100, .023)])
        self.assertNotIn("PRIVATE PERSON", repr(rows))


    def test_clear_lake_counts_individual_available_lots_only(self):
        page = """Industrial Park Addition to the City of Clear Lake.
        Lot 5 is SOLD. Lots 1, 2, 3, 4, 6 and 7 are still available."""
        self.assertEqual(adapters.parse_clear_lake_industrial_lots(page), ["1", "2", "3", "4", "6", "7"])
        self.assertEqual(adapters.parse_clear_lake_industrial_lots(page.replace("6 and 7", "5, 6 and 7")),
                         ["1", "2", "3", "4", "6", "7"])

    def test_clark_keeps_lots_in_acquisition_section_and_handles_missing_quote(self):
        page = """Below are properties currently owned by the Land Bank.
        <a href='/vacant-application.pdf'>Property Acquisition Application</a>
        <div>0 LYLE AVE, SPRINGFIELD 45505</div><div>P#: 300 07 00032 207 018</div>
        <div>Price: Auditor's Appraised Value</div>
        <footer>Where to Find Us 0 TEST ST, SPRINGFIELD 45506 P#: 301 06 00032 205 019 Price: Auditor's Appraised Value</footer>"""
        rows = adapters.parse_clark_oh_vacant(page)
        self.assertEqual([(r["apn"], r["price"], r["status"]) for r in rows], [("3000700032207018", None, "listed")])

    def test_athens_keeps_bundle_as_one_sale_and_excludes_pending(self):
        url = "https://athenscountylandbank.com/property/944-958-high-street-nelsonville/"
        metadata = {"@type": "Place", "name": "944/958 High Street, Nelsonville", "url": url,
                    "description": "Two vacant parcels. Parcel number(s): P030250011000, P030250011200",
                    "address": {"addressLocality": "Nelsonville", "streetAddress": "944 High Street"},
                    "geo": {"latitude": 39.4528808, "longitude": -82.235}}
        page = '<script type="application/ld+json">%s</script><div>Land Area 7000 sq ft Property Type Vacant Lots Property Status For Sale</div>' % json.dumps(metadata)
        row = adapters.parse_athens_oh_offer(page, url)
        self.assertEqual((row["apn"], row["acres"], row["lat"], row["price"]),
                         ("P030250011000, P030250011200", .1607, 39.4528808, None))
        self.assertIsNone(adapters.parse_athens_oh_offer(page.replace("For Sale", "Pending"), url))

    def test_rtc_washoe_uses_exact_notice_and_pacific_cutoff(self):
        page = """Property Disposals NOTICE OF INTENT TO SELL REAL PROPERTY BY SEALED BIDDING
        Assessors Parcel Numbers: APN 020-293-01 Address(es): Evelyn Circle Type of Property: Vacant Land
        Minimum Bid Amount: $220,500 (90% of fair market value) Down Payment Deposit (due with bid): $5,000
        Bid Deadline: 4:00 p.m. on December 7, 2026 Bid Opening: 10:00 a.m. on December 11, 2026
        Documents: Bid Proposal Form for APN 020-321-49"""
        row, = adapters.parse_rtc_washoe_sale(page, NOW)
        self.assertEqual((row["apn"], row["price"], row["deadline"]), ("020-293-01", 220500, "2026-12-08T00:00:00Z"))
        self.assertEqual(adapters.parse_rtc_washoe_sale(page, datetime.datetime(2026, 12, 8, tzinfo=datetime.timezone.utc)), [])


    def test_waycross_requires_available_status_and_reviewed_aerial_in_each_agency_table(self):
        head = '<table><tr><th>Parcel #</th><th>Commission District</th><th>Status &amp; Notes</th></tr>'

        def row(pin, doc, status):
            return ('<tr><td><a href="/DocumentCenter/View/%s"><img alt="Aerial view of parcel %s with the boundary outlined"></a></td>'
                    '<td>Marion Street</td><td>%s</td><td>0.34</td><td>R-75</td><td>2</td><td>%s</td></tr>') % (doc, pin, pin, status)

        page = (head + row("WA1805 078", 1228, "Available") + row("WA0710 070", 1179, "Available") + '</table>'
                + head + row("WA1902 010", 1192, "Available - multiple inquiries received")
                + row("WA0308 044", 1167, "Available - in discussion with adjoining owner") + '</table>')
        self.assertEqual([r[1] for r in adapters.parse_waycross_ga_offer_table(page, 0)], ["WA1805 078"])
        self.assertEqual([r[1] for r in adapters.parse_waycross_ga_offer_table(page, 1)], ["WA1902 010"])


    def test_huntington_notice_includes_vacant_and_excludes_improved_and_infrastructure(self):
        report = """Parcel ID     District     Address     Vacant/Structure
Zoning R-1 Single Family Residential
06-06-0056-0237-0000  West Huntington   HARVEY RD, HUNTINGTON 25701    Vacant
06-06-0056-0240-0000  West Huntington   ALLEY, HUNTINGTON 25701       Vacant
06-06-0066-0056-0000  West Huntington   1522 R WEST RD, HUNTINGTON 25701   Structure
"""
        self.assertEqual(adapters.parse_huntington_wv_notice(report), {
            "06-06-0056-0237-0000": ("Harvey Rd", "R-1 Single Family Residential"),
        })

    def test_oregon_dot_uses_live_status_and_withholds_appraisal_value(self):
        def item(status):
            return ("<entry><content><m:properties><d:Status>%s</d:Status><d:City>Eugene</d:City><d:County>Lane</d:County>"
                    "<d:Listing_x0020_Number>PM220A-041</d:Listing_x0020_Number>"
                    "<d:Description>Unimproved 1.87 acres parcel (17S04W2733 tax lot 1300).</d:Description>"
                    "<d:Address>Land parcel located along S. Bertelsen Road</d:Address><d:Price>650000</d:Price>"
                    "</m:properties></content></entry>") % status

        fixture = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
                   'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
                   + item("ON HOLD") + item("Active Listing") + '</feed>')
        row, = adapters.parse_oregon_dot_sales(fixture)
        self.assertEqual((row["apn"], row["acres"], row["price"]), ("17S04W2733-1300", 1.87, None))


    def test_grays_harbor_uses_purchase_price_and_excludes_sold_and_fractional_interests(self):
        text = """Parcel Number   Legal Desc    Situs Address (if any)   Assessed Value   Purchase Price   Available Until
026000601000    PORTLAND LOTS 10-18 INC BLK 6 - SOLD     $2,300.00   $1,741.61   12/2/2026
830501200500    ABER WAX EAST LOT 5 BLK 12   $609.00   $1,758.39   12/2/2026
029301700103    WAX & BENNS NLY 6' OF SLY 56' OF LOTS 1-3 INC BLK 17 UND 1/2 INT    $490.00    $375.00   9/14/2027
"""
        self.assertEqual(adapters.parse_grays_harbor_wa_roster(text, datetime.date(2026, 11, 27)), {
            "830501200500": (1758.39, "2026-12-02"),
        })
        self.assertEqual(adapters.parse_grays_harbor_wa_roster(text, datetime.date(2026, 12, 3)), {})

    def test_conejos_keeps_verified_vacant_auction_dates_without_guessing_bid_or_time(self):
        with self.assertRaises(adapters.StructureError):
            adapters.parse_conejos_co_notices("changed", NOW)
        rows = adapters.parse_conejos_co_notices(adapters.CONEJOS_CO_NOTICE_SHA256, NOW)
        self.assertEqual([(r["apn"], r["auction_day"], r["deadline"], r["price"]) for r in rows], [
            ("R571703300023", "2026-12-02", None, None), ("R556335202072", "2026-12-09", None, None),
        ])


    def test_elk_carries_named_vacant_parcel_without_assessment_or_prior_owner(self):
        text = """<h1>VACANT LAND – 40X IRR – Located in RIDGWAY TOWNSHIP</h1>
        <p>Address: 603 W MAIN ST</p><p>Parcel Number: 09-12-245-2459 &nbsp; /011950</p>
        <p>Owner: PRIVATE PERSON</p><p>Assessed Value: $10,985.76</p>"""
        row = adapters.parse_elk_pa_repo_parcel(text, adapters.ELK_PA_REPOSITORY)
        self.assertEqual((row["apn"], row["address"], row["locality"], row["price"]),
                         ("09-12-245-2459/011950", "603 W Main St", "Ridgway Township", None))
        self.assertNotIn("PRIVATE PERSON", repr(row))
        self.assertIsNone(adapters.parse_elk_pa_repo_parcel(text.replace("VACANT LAND", "BUILDING ONLY"), row["url"]))


class OfficialInventoryExtensionTest(unittest.TestCase):

    def test_metro_atlanta_matches_current_vacant_brochures_to_official_parcels(self):
        root = "https://metroatlantalandbank.org/wp-content/uploads/2024/08/"
        fetch = unittest.mock.Mock()
        fetch.text.return_value = '<h2>Simple Vacant Lots Available For Purchase</h2>' + ''.join(
            f'<a href="{root}{name}.pdf">View Lot</a>' for name in ("open", "inconsistent", "image-only"))
        sales = {"open.pdf": "Vacant Lot For Sale\nParcel ID#: 14 0040  LL0061\nApplication fee: $100",
                 "inconsistent.pdf": "Vacant Lot For Sale\nParcel ID#: 14 006700050493\n", "image-only.pdf": ""}
        rings = [[[-84.4, 33.7], [-84.4, 33.701], [-84.399, 33.7], [-84.4, 33.7]]]

        def official_record(pin, units):
            return {"attributes": {"ParcelID": pin, "Address": "0 LIVERMORE ST SE", "LandAcres": .61,
                                   "TaxYear": 2026, "LivUnits": units, "ClassCode": "E1", "LUCode": "600"},
                    "geometry": {"rings": rings}}

        features = [official_record("14 0040  LL0061", 0), official_record("14 006700050493", 1)]
        with patch.object(adapters, "pdf_text", side_effect=lambda fetch, url: sales[url.rsplit("/", 1)[-1]]), \
                patch.object(adapters, "arcgis_query", return_value=("https://example.com/gis", features)) as gis:
            rows, info = adapters.metro_atlanta_landbank(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual((info["upstream_total"], row["apn"], row["acres"], row["price"]), (3, "14 0040  LL0061", .61, None))
        self.assertTrue(row["geometry"])
        self.assertNotIn("Owner", gis.call_args.args[3])

    def test_denali_uses_the_current_count_and_the_linked_purchase_prices(self):
        fetch = unittest.mock.Mock()
        fetch.text.return_value = (
            '<p>The Denali Borough has two (2) lots for sale in the Panguingue Creek, Alaska Subdivision. '
            'Both lots are on Canopus Street.</p>'
            '<a href="&#xA; /vertical/sites/test/uploads/Panguingue_Creek_Subdivision_Land_for_Sale.pdf">'
            'Panguingue Creek Subdivision Land for Sale</a>'
        )
        table = ('All lots are available for sale at the listed, appraised value.\n'
                 '2021 AVAILABLE PROPERTY LIST\nBLOCK  LOT  ACERAGE  Appraised Value\n'
                 '16  2  5.00  $10,000\n16  3  5.00$10,000\nAppraised @\n')
        with patch.object(adapters, "pdf_text", return_value=table) as pdf:
            rows, result = adapters.denali_ak_land(fetch, NOW, self.fail)
            fetch.text.return_value = fetch.text.return_value.replace("two (2)", "one (1)")
            with self.assertRaises(adapters.StructureError):
                adapters.denali_ak_land(fetch, NOW, self.fail)
        self.assertEqual(result["upstream_total"], 2)
        self.assertEqual([(r["id"], r["acres"], r["price"], r["price_kind"]) for r in rows],
                         [("ak-denali-panguingue-16-2", 5, 10000, "cash"), ("ak-denali-panguingue-16-3", 5, 10000, "cash")])
        self.assertEqual(pdf.call_args.args[1],
                         "https://www.denaliborough.org/vertical/sites/test/uploads/Panguingue_Creek_Subdivision_Land_for_Sale.pdf")

    def test_alamosa_matches_certificate_parcel_and_date_with_vacancy(self):
        schedule = ('<h1>Upcoming Scheduled Public Auctions</h1><h3>December 2nd, 2026</h3><ul>'
                    '<li>Certificate 1, Parcel 541718108044, Private prior holder</li>'
                    '<li>Certificate 2, Parcel 541718108029</li>'
                    '<li>Certificate 3, Parcel 541718108022</li><li>Certificate 4, Parcel 541718108021</li>'
                    '</ul><h2>Archive</h2>')
        index = ('<a href="/DocumentCenter/View/1">Certificate 1, Parcel 541718108044 (PDF)</a>'
                 '<a href="/DocumentCenter/View/2">Certificate 2, Parcel 541718108031 (PDF)</a>'
                 '<a href="/DocumentCenter/View/3">Certificate 3, Parcel 541718108022 (PDF)</a>'
                 '<a href="/DocumentCenter/View/4">Certificate 4, Parcel 541718108021 (PDF)</a>')
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = [schedule, index]
        notice = ('PROPERTY ADDRESS: Vacant Land, Alamosa, CO. Private prior holder. '
                  'The property will be sold at public auction to the highest bidder at 8 am on Wednesday, December 2, 2026.')
        by_notice = {"1": notice, "3": notice.replace("Vacant Land", "Improved residence"),
                     "4": notice.replace("December 2", "December 3")}
        with patch.object(adapters, "pdf_text", side_effect=lambda fetch, url: by_notice[url.rsplit("/", 1)[-1]]) as pdf:
            rows, info = adapters.alamosa_co_tax_deed(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual((info["upstream_total"], row["apn"], row["price"], row["deadline"]),
                         (4, "541718108044", None, "2026-12-02T15:00:00+00:00"))
        self.assertNotIn("Private prior holder", repr(row))
        self.assertEqual(pdf.call_count, 3)

    def test_riverton_joins_only_signed_offer_lots_to_the_city_parcel_roll(self):
        import hashlib

        document = b"reviewed scanned lot prices and approved meeting minutes"
        digest = hashlib.sha256(document).hexdigest()
        terms = "https://cms2.revize.com/terms.pdf"
        approval = "https://cms2.revize.com/approval.pdf"
        fetch = unittest.mock.Mock()
        fetch.bytes.return_value = document
        rings = [[[-108.46, 43.07], [-108.46, 43.071], [-108.459, 43.07], [-108.46, 43.07]]]

        def record(pin, lot, street="PIPER DR"):
            return {"attributes": {"parcelnb": pin, "legal": f"RIW INDUSTRIAL PARK FIRST ADDITION: LOT {lot}",
                                   "taxyear": "2026", "landgrossa": 1.2764, "locationad": street},
                    "geometry": {"rings": rings}}

        records = [record("91141830600100", 1), record("91141830600200", 2, "CESSNA DR"),
                   record("91141830600300", 3)]
        with patch.object(adapters, "RIVERTON_WY_DOCS", {"terms": (terms, digest), "approval": (approval, digest)}), \
                patch.object(adapters, "arcgis_query", return_value=("https://example.com/gis", records)) as gis:
            rows, info = adapters.riverton_wy_industrial(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual((info["upstream_total"], row["apn"], row["price"], row["acres"], row["price_kind"]),
                         (4, "91141830600100", 38000, 1.2764, "asking"))
        self.assertTrue(row["geometry"])
        self.assertIn("UPPER(ownername1)='RIVERTON CITY OF'", gis.call_args.args[2])
        self.assertNotIn("ownername", gis.call_args.args[3])

    def test_firstpark_requires_available_marker_and_matching_sale_detail(self):
        def lot_marker(number, status, buildable="5.4"):
            return (f'<g class="interactive lot-group" data-status="{status}" data-name="Lot {number}" '
                    f'data-total="10.4" data-buildable="{buildable}" data-road="FirstPark Drive" '
                    f'data-url="/available-lots/firstpark-lot-{number}/"></g>')

        directory = adapters.FIRSTPARK_ME
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = {
            directory: lot_marker(4, "available") + lot_marker(5, "available") + lot_marker(6, "sold"),
            directory + "firstpark-lot-4/": "<h1>FirstPark Lot 4</h1><p>For Sale or Build to Suit</p>",
            directory + "firstpark-lot-5/": "<h1>FirstPark Lot 50</h1><p>For Sale or Build to Suit</p>",
        }.__getitem__
        rows, info = adapters.firstpark_me_lots(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual((info["upstream_total"], row["id"], row["acres"], row["price"]),
                         (3, "me-firstpark-lot-4", 10.4, None))
        self.assertIn("5.4 buildable acres in the authority’s lot directory",
                      [fact["value"] for fact in row["facts"]])
        self.assertIsNone(row["geometry"])

    def test_certified_site_requires_current_public_sale_and_preserves_rate(self):
        from lando.pages import price_line

        fields = {
            "Site Ownership": "Public", "For sale or lease": "Sale", "County": "Washington",
            "Site Acreage": "22 acres", "Sale/lease price": "$40,000 /acre",
        }

        def profile(overrides):
            return "".join(f'<div class="acf-field-name">{key}</div><div class="acf-field-value">{value}</div>'
                           for key, value in (fields | overrides).items())

        page = "https://tnecd.com/certifiedsite/test-site/"
        entry = {"id": 101, "status": "publish", "link": page, "title": {"rendered": "Test industrial site"},
                 "acf": {"sold": False, "is_sold": "no", "latitude": "36.263925", "longitude": "-82.5598363"}}
        sold = {**entry, "id": 102, "acf": {**entry["acf"], "sold": True}}
        fetch = unittest.mock.Mock()
        fetch.json.return_value = [entry, sold]
        fetch.text.return_value = profile({})
        rows, info = adapters.tnecd_certified_sites(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual((info["upstream_total"], row["acres"], row["price"], row["lon"]), (2, 22, None, -82.5598363))
        self.assertIn("$40,000 /acre", [fact["value"] for fact in row["facts"]])
        self.assertEqual(price_line(row), "$40,000 /acre")
        fetch.text.assert_called_once_with(page)
        for change in ({"For sale or lease": "Lease"}, {"Site Ownership": "Private"}, {"Site Acreage": "22–60 acres"}):
            self.assertIsNone(adapters.parse_tnecd_certified_detail(entry, profile(change)))

    def test_washington_county_joins_current_surplus_to_exact_vacant_records(self):
        fetch = unittest.mock.Mock()
        fetch.text.return_value = ('<a href="/DocumentCenter/View/1/COUNTY-OWNED-PROPERTY">Roster</a>'
                                   'Interested parties interested in acquiring one or more of these parcels.')
        roster = ('MAP    GROUP   PARCEL    ADDRESS #     STREET       ACREAGE ACQUIRED\n'
                  '022M     A      03000 000   TEST ROAD  0.40\n'
                  '046K     C      02800 000   TEST ROAD  1.00\n'
                  '38              03001 000   TEST ROAD  .58 ac\n'
                  '013H     A      01502 000   TEST ROAD  SLIVER\n'
                  '054D     E      03201 000   TEST ROAD  3.5 x 150\n')
        rings = [[[-82.40, 36.35], [-82.40, 36.351], [-82.399, 36.35], [-82.40, 36.35]]]
        def make_record(pin, improvements):
            return {"attributes": {"GISLINK": pin, "BLDGS": 0, "NUM_MH": 0, "IMPVAL": improvements, "CALC_ACRE": .61},
                    "geometry": {"rings": rings}}
        features = [make_record("090038    03001", 0), make_record("090046K C 02800", 1000),
                    make_record("090054D E 03201", 0)]
        with patch.object(adapters, "pdf_text", return_value=roster), \
                patch.object(adapters, "arcgis_query", return_value=("", features)) as gis:
            rows, info = adapters.washington_tn_surplus(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual((info["upstream_total"], row["apn"], row["acres"], row["price"]), (3, "038 03001 000", .61, None))
        self.assertIn("UPPER(OWNER) IN ('WASHINGTON COUNTY'", gis.call_args.args[2])
        self.assertNotIn("OWNER", gis.call_args.args[3])
        self.assertTrue(row["geometry"])

    def test_greybull_requires_current_town_assessment_and_keeps_industrial_price_per_acre(self):
        import hashlib
        import io
        import zipfile

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("parcel_ownership.dbf", b"assessment fixture")
        document = b"verified document"
        digest = hashlib.sha256(document).hexdigest()
        documents = {key: (url, digest) for key, (url, _) in adapters.GREYBULL_DOCS.items()}
        fetch = unittest.mock.Mock()
        fetch.text.return_value = "Frontier Subdivision Map Industrial park lots available " + " ".join(
            url for url, _ in documents.values())
        fetch.bytes.side_effect = lambda url: archive.getvalue() if url.endswith(".zip") else document
        holder = "TOWN OF GREYBULL"
        assessments = [
            ("R0015482", "312", "", holder, 5.79, None),
            ("R0015444", "292", "19-22", "PRIVATE PARTY", 3.20, None),
            ("R0015282", "292", "34-36", holder, 2.41, 500),
            ("R0015299", "307", "40-58 & 67-68", holder, 17.19, None),
        ]
        keys = ("accountno", "subno", "lot", "name", "grossacres", "impsval")
        shapefile = unittest.mock.MagicMock()
        reader = shapefile.Reader.return_value.__enter__.return_value
        reader.iterRecords.return_value = [unittest.mock.Mock(**{"as_dict.return_value": dict(zip(keys, row))})
                                          for row in assessments]
        with patch.dict("sys.modules", {"shapefile": shapefile}), patch.object(adapters, "GREYBULL_DOCS", documents):
            rows, info = adapters.greybull_wy_land(fetch, NOW, self.fail)
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(info["upstream_total"], 21)
        self.assertEqual(by_id["wy-greybull-frontier-lot-29"]["price"], 39780)
        self.assertIsNone(by_id["wy-greybull-industrial-lot-56"]["price"])
        self.assertNotIn("wy-greybull-industrial-lot-67", by_id)
        self.assertNotIn("PRIVATE PARTY", repr(rows))

    def test_franklin_adjacent_sale_requires_adopted_schedule_and_keeps_combined_bid(self):
        import hashlib

        fetch = unittest.mock.Mock()
        fetch.text.return_value = 'November 10, 2026 duly adopted the following ordinance: O-18-26'
        fetch.bytes.return_value = b'verified schedule'
        document = {adapters.FRANKLIN_NJ_ROSTER: hashlib.sha256(fetch.bytes.return_value).hexdigest()}
        offered = (("1001", ("4", "5"), "Stanton Avenue", 37800, .89),)
        rings = [[[-75.06, 39.61], [-75.06, 39.611], [-75.059, 39.611], [-75.059, 39.61], [-75.06, 39.61]]]
        records = [{"attributes": {"PAMS_PIN": "0805_1001_" + lot, "IMPRVT_VAL": 0}, "geometry": {"rings": rings}}
                   for lot in ("4", "5")]
        with patch.object(adapters, "FRANKLIN_NJ_DOCUMENTS", document), patch.object(adapters, "FRANKLIN_NJ_OFFERS", offered), \
                patch.object(adapters, "_arcgis_query", return_value=records):
            rows, info = adapters.franklin_nj_adjacent_land(fetch, NOW, self.fail)
            row, = rows
            self.assertEqual(info["upstream_total"], 1)
            self.assertEqual((row["apn"], row["price"], row["deadline"]), ("1001-4 / 1001-5", 37800, "2026-12-02T15:00:00Z"))
            self.assertIn("adjacent buyers only", row["tags"])
            fetch.bytes.return_value = b'updated schedule'
            with self.assertRaises(adapters.StructureError):
                adapters.franklin_nj_adjacent_land(fetch, NOW, self.fail)

    def test_chelan_tax_auction_checks_improvements_and_keeps_balance_out_of_price(self):
        schedule = ('<p>Online sale will be held Dec. 7, 2026, through Dec. 9, 2026.</p>'
                    '<table><tr><td>26258</td><td>PRIVATE PERSON</td><td>$5,123.00</td>'
                    '<td>UNASSIGNED</td><td>WENATCHEE WA</td></tr>'
                    '<tr><td>43034</td><td>PRIVATE PERSON</td><td>$181.92</td>'
                    '<td>103 N PARK (TIMESHARE UNIT)</td><td>CHELAN WA</td></tr></table>')
        assessor = ('Year 2026 - 2027 Property ID: 26258 Geographic ID: 232033110220 Land Use Code 11 '
                    'Legal Acres: 0.8800 Improvement Homesite Value: + $0 Improvement Non-Homesite Value: + $0')
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = [schedule, assessor]
        rings = [[[-120.31, 47.42], [-120.31, 47.421], [-120.309, 47.421],
                  [-120.309, 47.42], [-120.31, 47.42]]]
        gis = [{"attributes": {"ORIG_PARCEL_ID": "232033110220", "VALUE_BLDG": 0}, "geometry": {"rings": rings}}]
        with patch.object(adapters, "_arcgis_query", return_value=gis):
            rows, info = adapters.chelan_wa_auction(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual(info["upstream_total"], 1)
        self.assertEqual((row["apn"], row["price"], row["acres"], row["auction_day"]),
                         ("232033110220", None, .88, "2026-12-09"))
        self.assertNotIn("PRIVATE PERSON", repr(row))
        improved = assessor.replace("Improvement Homesite Value: + $0", "Improvement Homesite Value: + $5,000")
        self.assertIsNone(adapters.parse_chelan_wa_assessment(improved, "26258", 2026))

    def test_douglas_tax_title_uses_current_minimum_and_preserves_access_restriction(self):
        fetch = unittest.mock.Mock()
        fetch.text.return_value = '<a href="/current.pdf">Douglas County - Tax Title Properties</a>'
        roster = ('Below is the current list of tax title properties. If you are interested in purchasing:\n'
                  'Parcel: 01400804000\n'
                  f'Minimum Bid: $ 747.02 ({adapters.DOUGLAS_WA_NO_ACCESS})\n'
                  'Parcel: 24 21 18 300 03\nMinimum Bid: $ 243.45 (Parcel completely under water)\n'
                  'Parcel: 40200005501\nMinimum Bid: $ 1,065.31\n')
        rings = [[[-119.68, 48.0], [-119.68, 48.001], [-119.679, 48.001],
                  [-119.679, 48.0], [-119.68, 48.0]]]
        gis = [{"attributes": {"ORIG_PARCEL_ID": "01400804000", "LANDUSE_CD": 91, "VALUE_BLDG": 0, "VALUE_LAND": 500},
                "geometry": {"rings": rings}},
               {"attributes": {"ORIG_PARCEL_ID": "40200005501", "LANDUSE_CD": 45, "VALUE_BLDG": 0, "VALUE_LAND": 500},
                "geometry": {"rings": rings}}]
        with patch.object(adapters, "pdf_text", return_value=roster), patch.object(adapters, "_arcgis_query", return_value=gis):
            rows, info = adapters.douglas_wa_tax_title(fetch, NOW, self.fail)
        row, = rows
        self.assertEqual(info["upstream_total"], 2)
        self.assertEqual((row["apn"], row["price"], row["price_kind"]), ("01400804000", 747.02, "min_bid"))
        self.assertIn(adapters.DOUGLAS_WA_NO_ACCESS, [f["value"] for f in row["facts"]])
        self.assertTrue(row["geometry"])

    def test_nevada_county_keeps_open_priced_unimproved_parcels(self):
        schedule = ('<p>Auction Date: January 7, 2027</p>'
                    '<a href="/list.pdf">2026 Auction Property List</a>')
        roster = ('Online Auction Dates: January 7, 2027 Auction Begins: 10:00 am PST\n'
                  'PARCEL NUMBER LAST ASSESSED OWNER MINIMUM BID SALE STATUS\n'
                  '047-180-024-000            PRIVATE PERSON        $5,036.00\n'
                  '052-060-004-000            PRIVATE PERSON        $3,023.00   REDEEMED\n'
                  '008-190-017-000            PRIVATE PERSON        $33,133.00\n')
        fetch = unittest.mock.Mock()
        fetch.text.return_value = schedule
        gis = [{"attributes": {"APN": "047180024000", "UseCode": "2000", "Status": "A", "Acreage": .19, "TotalImproveValue": 0}},
               {"attributes": {"APN": "008190017000", "UseCode": "0100", "Status": "A", "TotalImproveValue": 2000}}]
        with patch.object(adapters, "pdf_text", return_value=roster), patch.object(adapters, "_arcgis_query", return_value=gis):
            rows, info = adapters.nevada_ca_tax_sale(fetch, NOW, self.fail)
            self.assertEqual(info["upstream_total"], 2)
            row, = rows
            self.assertEqual((row["apn"], row["price"], row["auction_day"], row["deadline"]),
                             ("047-180-024-000", 5036, "2027-01-07", None))
            self.assertNotIn("PRIVATE PERSON", repr(row))
            expired, _ = adapters.nevada_ca_tax_sale(fetch, NOW + datetime.timedelta(days=52), self.fail)
            self.assertEqual(expired, [])

    def test_atlantic_requires_a_reviewed_vacant_map_and_keeps_assessment_out_of_price(self):
        import hashlib

        page = ('<p>To purchase a City-owned vacant lot, complete the bid form.</p>'
                '<p>Current Available Properties for Sale</p>'
                '<p>1106 Poplar Street<br />Size: 7,500 sq. ft.<br />Assessed Value: $8,180</p>'
                '<p><img src="/map.png"></p><a>Policy for Disposition</a>')
        fetch = unittest.mock.Mock()
        fetch.text.return_value = page
        fetch.bytes.return_value = b"reviewed exhibit"
        approved = {"1106 Poplar Street": hashlib.sha256(fetch.bytes.return_value).hexdigest()}
        with patch.object(adapters, "ATLANTIC_IA_VACANT_IMAGES", approved):
            rows, _ = adapters.atlantic_ia_land(fetch, NOW, self.fail)
            row, = rows
            self.assertEqual((row["address"], row["acres"], row["price"]), ("1106 Poplar Street", .1722, None))
            fetch.bytes.return_value = b"replacement map"
            with self.assertRaises(adapters.StructureError):
                adapters.atlantic_ia_land(fetch, NOW, self.fail)

    def test_clinton_preserves_combined_offers_and_rejects_improved_parcels(self):
        page = ('<h2>Disposition of City-Owned Buildable Lots</h2><p>We sell buildable, bare ground lots.</p>'
                '<table><tr><td>1 Main</td><td>80-1234-0000 &amp; 80-1235-0000</td><td>Irreg.</td></tr>'
                '<tr><td>2 Main</td><td>80-1236-0000</td><td>30 x 100</td></tr></table>')
        fetch = unittest.mock.Mock()
        fetch.text.return_value = page
        gis = [{"attributes": {"Parcel_ID": key, "Dwelling_Value": 0, "Improvement_Value": improvements, "Graphic_Ac": acres}}
               for key, improvements, acres in (("8012340000", 0, .1), ("8012350000", 0, .15), ("8012360000", 200, .07))]
        with patch.object(adapters, "_arcgis_query", return_value=gis):
            rows, info = adapters.clinton_ia_land(fetch, NOW, self.fail)
        self.assertEqual(info["upstream_total"], 2)
        row, = rows
        self.assertEqual((row["apn"], row["acres"], row["price"]), ("80-1234-0000 / 80-1235-0000", .25, None))

    def test_centerville_only_currently_offers_explicit_bare_lots(self):
        fetch = unittest.mock.Mock()
        fetch.text.return_value = ('<p>Properties currently owned by the City and available for development. '
                                   'Contact the city about purchasing a property for residential construction.</p>'
                                   '<p>340011020660000&nbsp;515 N. Park&nbsp;<strong>Bare Lot</strong></p>'
                                   '<p>340011015650000&nbsp;418 E. Van Buren&nbsp;Derelict Structure</p>')
        rows, info = adapters.centerville_ia_land(fetch, NOW, self.fail)
        self.assertEqual(info["upstream_total"], 2)
        row, = rows
        self.assertEqual((row["apn"], row["address"], row["price"]), ("340011020660000", "515 N. Park", None))
        fetch.text.return_value = '<p>340011020660000 515 N. Park Bare Lot</p>'
        with self.assertRaises(adapters.StructureError):
            adapters.centerville_ia_land(fetch, NOW, self.fail)

    def test_providence_requires_fee_simple_and_uses_published_close(self):
        import io
        from zipfile import ZipFile

        def document(offer):
            word = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                    '<w:p><w:r><w:t>246 Prairie Avenue (Plat 45/Lot 911)</w:t></w:r></w:p>'
                    '<w:p><w:r><w:t>The Agency cleared the site of its structures. As the Property is 4.6 acres,</w:t></w:r></w:p>'
                    '<w:p><w:r><w:t>The Agency will consider proposals that offer either %s.</w:t></w:r></w:p>'
                    '<w:p><w:r><w:t>PROPOSAL SUBMISSIONS</w:t><w:br/>'
                    '<w:t>Proposals are due Friday December 4</w:t></w:r>'
                    '<w:r><w:t>th</w:t></w:r><w:r><w:t>, 2026 by 4:00 PM</w:t></w:r></w:p></w:body></w:document>') % offer
            package = io.BytesIO()
            with ZipFile(package, "w") as doc:
                doc.writestr("word/document.xml", word)
            return package.getvalue()

        fetch = unittest.mock.Mock()
        fetch.text.return_value = '<a href="/offer.docx">View the 246 Prairie Avenue RFP</a>'
        fetch.bytes.return_value = document("fee simple land acquisition, or ground lease")
        rings = [[[-71.4, 41.81], [-71.399, 41.81], [-71.4, 41.811], [-71.4, 41.81]]]
        match = {"attributes": {"PlatLot": "PR 045-0911-0000"}, "geometry": {"rings": rings}}
        with patch.object(adapters, "_arcgis_query", return_value=[match, match]) as query:
            rows, _ = adapters.providence_ri_prairie(fetch, NOW, self.fail)
            row, = rows
            self.assertEqual((row["acres"], row["price"], row["deadline"]), (4.6, None, "2026-12-04T21:00:00Z"))
            self.assertTrue(row["geometry"])
            expired, _ = adapters.providence_ri_prairie(fetch, NOW + datetime.timedelta(days=13), self.fail)
            self.assertEqual(expired, [])
            self.assertEqual(query.call_count, 1)
        fetch.bytes.return_value = document("a ground lease")
        with self.assertRaises(adapters.StructureError):
            adapters.providence_ri_prairie(fetch, NOW, self.fail)

    def test_lidgerwood_lists_only_reviewed_vacant_lot_and_rechecks_minutes(self):
        import hashlib

        names = tuple(adapters.LIDGERWOOD_ND_EVIDENCE)
        market = ('<h1>Residential Lots For Sale</h1><p>Submit a letter of intent</p>'
                  f'<a href="{adapters.LIDGERWOOD_ND_LIST}">List</a>')
        minutes = ''.join(f'<a class="link" href="/uploads/{name}">Minutes</a>' for name in names[1:])
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = [market, minutes, market, minutes]
        fetch.bytes.return_value = b"reviewed document"
        hashes = dict.fromkeys(names, hashlib.sha256(fetch.bytes.return_value).hexdigest())
        with patch.object(adapters, "LIDGERWOOD_ND_EVIDENCE", hashes):
            rows, _ = adapters.lidgerwood_nd_lots(fetch, NOW, self.fail)
            row, = rows
            self.assertEqual((row["apn"], row["price"]), ("47-0001-03190.000", None))
            fetch.bytes.return_value = b"updated council disposition"
            with self.assertRaises(adapters.StructureError):
                adapters.lidgerwood_nd_lots(fetch, NOW, self.fail)

    def test_claremont_requires_current_marketing_and_a_vacant_assessment(self):
        sale = '<h2>Commercial Industrial Lots for Sale in the Syd Clarke Industrial Park</h2>'
        roster = '<p>Syd Clarke Drive: 187-2, 187-2-5, 187-2-6</p><p>Ashleys Landing: 163-3</p>'
        card = ('Current Value Appraisal Valuation Year Improvements Land Total 2026 $0 $24,000 '
                'Land Use Use Code 928V Description CDA MDL-00 Zone I3 Living Area: 0 '
                'No Data for Outbuildings No Data for Extra Features Line Valuation Size (Acres) 2.08')
        features = [{"attributes": {"pid": "187-2-" + lot, "u_id": "4042-" + lot, "streetaddress": "SYD CLARKE DR"}}
                    for lot in ("5", "6")]
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = [sale, roster, card, card.replace("$0", "$12,000")]
        with patch.object(adapters, "_arcgis_query", return_value=features) as query:
            rows, info = adapters.claremont_nh_industrial(fetch, NOW, self.fail)
        self.assertEqual(info["upstream_total"], 2)
        self.assertEqual([(row["apn"], row["acres"], row["price"]) for row in rows], [("187-2-5", 2.08, None)])
        self.assertNotIn("163-3", query.call_args.args[2])
        fetch.text.side_effect = ['<h2>Syd Clarke Industrial Park</h2>']
        self.assertEqual(adapters.claremont_nh_industrial(fetch, NOW, self.fail)[0], [])

    def test_todd_vacant_land_preserves_cash_price_without_inferring_a_minimum_bid(self):
        property_text = ("31-0004800  4th Street\n"
                         "  Appraised Value: $6,900.00\n"
                         "  Sale Price: Fees are not included $4,650.00\n"
                         "  Type: Residential Vacant\n"
                         "  Approximate Lot Size: .42 Acres\n"
                         "33-0016300  229 Clark Street\n"
                         "  Sale Price: Fees are not included $3,900.00\n"
                         "  Type: Residential\n")
        otc, = adapters.parse_todd_mn_land("Tax forfeited parcel to purchase over the counter\n" + property_text, "https://county.example")
        auction, = adapters.parse_todd_mn_land("AUCTION LISTING TAX FORFEITED PARCELS\n" + property_text, "https://county.example",
                                              datetime.date(2026, 12, 15))
        self.assertEqual((otc["price"], otc["price_kind"], otc["acres"]), (4650, "cash", .42))
        self.assertEqual((auction["price"], auction["deadline"], auction["auction_day"]), (None, None, "2026-12-15"))

    def test_dorchester_notice_keeps_exact_open_unimproved_accounts_and_closing_time(self):
        directory = ('<span class="BidDetail"></span><div class="listItemsRow bid">'
                     '<a href="bids.aspx?bidID=6">Sale of County-Owned Properties</a>'
                     '<span>Open</span><br><span>12/1/2026 1:59 PM</span>'
                     '<div class="listItemsRow bid alt"><a href="bids.aspx?bidID=7">Sale of County-Owned Properties</a>'
                     '<span>Closed</span><br><span>12/1/2026 2:00 PM</span>')
        notice = ('<meta property="og:description" content="Closing Date/Time: 12/1/2026 1:59 PM" />'
                  '<p>No minimum bid amounts are as follows:</p>'
                  '<p>• Account # 07179588: N/S Town Point Rd</p>'
                  '<p>• Account # 06086721: 1612 Steamboat Wharf Rd</p><p>Sealed bids, clearly marked</p>')
        fetch = unittest.mock.Mock()
        fetch.text.side_effect = [directory, notice]
        matched = [
            {"attributes": {"ACCTID": "1007179588", "NFMLNDVL": 1000, "NFMTTLVL": 1000, "ACRES": .5}},
            {"attributes": {"ACCTID": "1006086721", "NFMLNDVL": 1000, "NFMTTLVL": 1000, "YEARBLT": "1940"}},
        ]
        with patch.object(adapters, "_arcgis_query", return_value=matched):
            rows, info = adapters.dorchester_md_real_property(fetch, NOW, self.fail)
        self.assertEqual(info["upstream_total"], 2)
        row, = rows
        self.assertEqual((row["apn"], row["price"], row["deadline"]), ("07179588", None, "2026-12-01T18:59:00Z"))
        self.assertEqual(fetch.text.call_count, 2)

    def test_valencia_uses_only_known_unimproved_subdivision_lots(self):
        attrs = {"UPC": "1019038365253000000", "AccountNum": "R027369", "IMPACT": 0,
                 "Subdivisio": "MEADOW LAKE SUBDIVISION", "Lot": "12", "Situs": "",
                 "Owner": "PRIVATE PERSON"}
        rings = [[[-106.7, 34.8], [-106.6998, 34.8], [-106.6998, 34.8002], [-106.7, 34.8002], [-106.7, 34.8]]]
        sample = {"attributes": attrs, "geometry": {"rings": rings}}
        r = adapters.valencia_lot_listing(sample, "valencia-county-land", adapters.VALENCIA_BUY)
        self.assertGreater(r["acres"], 0)
        self.assertIsNone(r["price"])
        self.assertNotIn("PRIVATE PERSON", repr(r))
        for change in ({"IMPACT": 100}, {"Subdivisio": "COUNTY LANDFILL"}, {"Situs": "120 MAIN ST"}):
            sample["attributes"] = {**attrs, **change}
            self.assertIsNone(adapters.valencia_lot_listing(sample, "valencia-county-land", adapters.VALENCIA_BUY))

    def test_valencia_auction_uses_only_minimum_bid_and_expires(self):
        text = ("Public auction in Valencia County\nTIME: 10:00 AM\nDATE: Tuesday, December 15, 2026\n"
                "Item #1 Case: 1\nUPC: 1019038365253000000\nDelinquent Owner: PRIVATE PERSON\nMinimum Bid: $2,400.00\n"
                "Item #2 Case: 2\nUPC: 1019038365253000001\nMinimum Bid: $4,000.00\nProperty Description: LOT 11 MH#123\n"
                "Item #3 Case: 3 REMOVED\nUPC: 1019038365253000002\nMinimum Bid: $1,200.00\n")
        bids, deadline = adapters.parse_valencia_auction(text, NOW)
        self.assertEqual(bids, {"1019038365253000000": 2400})
        self.assertEqual(deadline, "2026-12-15T17:00:00Z")
        self.assertEqual(adapters.parse_valencia_auction(text, NOW + datetime.timedelta(days=30)), ({}, None))

    def test_st_louis_county_omits_sold_and_improved_tracts(self):
        text = ("Current parcels for immediate purchase\n over the counter at the listed price\n"
                "Tract 1       CITY OF DULUTH      010-0070-00210      $18,000.00     ± 1.26 acres       C22250063\n"
                "Improvements      $0.00\nTotal       $18,000.00\n"
                "Tract 2       CITY OF DULUTH      010-0070-00390      $35,300.00     ± 2.13 acres       C22250065\n"
                "SOLD\nImprovements      $0.00\nTotal       $35,300.00\n"
                "Tract 3       CITY OF DULUTH      010-0220-03930      $32,600.00     ± 1.34 acres       C22250066\n"
                "Improvements      $250.00\nTotal       $32,600.00\n")
        rows = adapters.parse_stlouis_mn_book(text, adapters.STLOUIS_MN_URL)
        self.assertEqual([(row["apn"], row["price"], row["acres"]) for row in rows], [("010-0070-00210", 18000, 1.26)])

    def test_fairbanks_offers_only_named_lot_sheets_at_published_price(self):
        page = ('Available lots are sold at their established fair market value.'
                '<a target="_blank" href="/DocumentCenter/View/27480/WCRR-Lot-7-FMV-12300">WCRR Lot 7 (FMV $12,300)</a>'
                '<a href="/DocumentCenter/View/27481/WCRR-Lot-8-FMV-11500">WCRR Lot 8 (sold)</a>')
        rows = adapters.parse_fnsb_chatanika(page)
        self.assertEqual([(row["id"], row["price"]) for row in rows], [("ak-fnsb-chatanika-7", 12300)])
