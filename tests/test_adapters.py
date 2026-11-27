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
