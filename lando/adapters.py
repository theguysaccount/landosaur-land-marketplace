"""One adapter per official source. Each returns (listings, info) or raises when the source's structure changed.

Every listing links to its official source page. Only facts about the land and the offering are kept: no names of
previous owners, no photographs, no marketing text. Prices are never invented: a source without a price gets none.

    listing = {id, source, title, state, county, locality, apn, acres, price, price_kind, offering, status,
               deadline, url, address, lat, lon, geometry, facts, tags}
"""
import csv
import datetime
import hashlib
import html
import io
import json
import math
import re
import urllib.parse

from .net import FetchError

STATUS = {  # status -> (label, still available to buy)
    "listed": ("Listed by the agency", True),
    "availability_unverified": ("Sale availability unconfirmed", False),
    "auction_open": ("Auction: bidding open", True),
    "auction_terms": ("Auction or tax sale: see terms", True),
    "proposal_open": ("Proposals invited", True),
    "pending": ("Sale pending", False),
    "auction_closed": ("Bidding closed", False),
}
PRICE_KIND = {"cash": "Price", "min_bid": "Minimum bid", "application": "Program price", "none": "No price published"}


class StructureError(Exception):
    """The source answered, but not in the shape this adapter knows. Last good data is kept."""


def clean(text):
    text = re.sub(r"(?is)<br\s*/?>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(html.unescape(text).replace("\xa0", " ").split())


def number(text):
    if text is None:
        return None
    m = re.search(r"-?[\d,]*\.?\d+", str(text))
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None


NOTES = {  # long notes repeated on many listings are stored by key and expanded when pages are built
    "stl_available": "The city's full inventory lists this parcel as available. Only available vacant lots are included; buildings and unavailable parcels are left out. Buying requires the city's application and review.",
    "stl_area": "Listed square footage; acres = square feet / 43,560. Not a survey.",
    "stl_price": "The city sets terms through its application process. No price is shown here because none is published.",
    "stl_side_lot": "The city's side-lot program can let a neighbouring owner buy a lot; confirm eligibility with the city.",
    "ar_bid": "The Commissioner of State Lands' minimum bid. Not a purchase price or appraisal: tax-sale title, redemption rights, condition and improvements need review.",
    "ar_apn": "County assessor parcel number as listed by the Commissioner.",
    "ar_window": "Read from the Commissioner's auction grid; confirm the exact cutoff and sale conditions on the listing.",
    "outline": "GIS reference boundary from the agency, not a survey. The map pin is the outline's centre.",
    "access_attr": "A listing attribute; it does not establish recorded or year-round access.",
    "dlba_program": "Published in the Detroit Land Bank Authority open-data GIS inventory as an actively marketed lot program. Confirm eligibility, pricing, and purchase rules on buildingdetroit.org.",
    "dlba_price": "Pricing depends on the specific Detroit Land Bank program and application review. No asking price is published in the GIS feed.",
    "kc_available": "Listed as Acquired in the Kansas City, Missouri Open Data Land Bank inventory (vacant land classes only). Confirm current availability and purchase terms with the Land Bank of Kansas City.",
    "kc_price": "The Land Bank of Kansas City reviews purchase applications and sets sale terms per parcel. Assessor market values are not asking prices and are not shown as list prices.",
    "ca_proposal": "Official California DGS development or surplus property proposal notice. Not an unconditional cash sale; confirm eligibility, lease/sale terms, and exact cutoff with California DGS.",
    "chi_program": "Published in the City of Chicago City-Owned Land Inventory (ChiBlockBuilder). Confirm current eligibility, offer round rules, and pricing directly with the City of Chicago DPD.",
    "chi_val": "City open-data land valuation figure, not an asking price or market appraisal.",
    "pgh_avail": "Listed as Vacant Land / Available for Sale (Public Sale) in the City of Pittsburgh daily open-data inventory (WPRDC). Buying requires city/land-bank review and application.",
    "lou_avail": "Listed as Available Lot in the Louisville Metro Landbank Authority GIS parcel inventory. Confirm program eligibility, pricing, and application deadlines with Louisville Metro.",
    "lucas_avail": "Vacant land parcel held in the Lucas County Land Bank GIS inventory. Confirm current availability, program requirements, and pricing on lucascountylandbank.org.",
    "la_ttc_bid": "Minimum bid published in the Los Angeles County Treasurer & Tax Collector auction GIS layer. Not a final sale price or appraisal; verify current auction schedule, redemption status, and terms on ttc.lacounty.gov.",
    "broward_surplus": "County-owned surplus real property parcel published in Broward County GIS. Confirm current sale status, bidding method, and liens with Broward County and the Property Appraiser.",
    "udot_surplus": "Unsold surplus right-of-way parcel published in Utah DOT GIS. Confirm availability, appraisal/auction process, and access restrictions with UDOT Right of Way.",
    "albany_lb": "Vacant land parcel held by the Albany County Land Bank Corp. Confirm current availability, eligibility, and program pricing on albanycountylandbank.org.",
    "orange_fl_tda": "Active Orange County, Florida Tax Deed Sale parcel with posted auction date. Confirm opening bid, statutory redemption cutoff, title/liens, and auction registration with the Orange County Comptroller.",
    "lascruces_vac": "City-owned vacant land parcel published in the City of Las Cruces GIS inventory. Confirm surplus disposition availability and zoning directly with the City of Las Cruces.",
    "baltimore_vac": "City-owned vacant parcel in Baltimore's official GIS inventory. Confirm Buy Into Baltimore / DHCD availability, pricing, and rehabilitation terms directly with Baltimore City DHCD.",
    "bigspring_tx": "City-owned vacant lot published by the City of Big Spring / Howard County GIS. Confirm current surplus availability, bidding process, and liens with the City of Big Spring.",
    "king_wa": "Tax-title vacant land held by King County Real Estate Services after tax foreclosure. Confirm current availability, minimum bid, easements, and sale procedures on kingcounty.gov.",
    "charlotte_nc": "Undeveloped city-owned land parcel published in City of Charlotte GIS. Confirm surplus disposition eligibility and zoning directly with the City of Charlotte.",
    "canton_ga": "City-owned parcel published by the City of Canton / Cherokee County GIS. Confirm surplus availability and zoning directly with the City of Canton.",
    "sanmiguel_co": "County-owned parcel published by San Miguel County GIS. Confirm whether the tract is available for surplus sale or public auction with San Miguel County.",
    "navajo_az": "Back-tax auction parcel published by Navajo County GIS with direct auction listing link. Confirm bidding window, opening bid, road access, and title terms directly on the auction page.",
    "ebr_la": "Adjudicated tax-sale parcel published by East Baton Rouge Parish Open Data. Under Louisiana adjudicated property statutes, confirm redemption status, purchase process, and title requirements with the parish.",
    "cherryhill_nj": "Township-owned vacant lot published in Cherry Hill / Camden County GIS. Confirm municipal land sale auction schedule and minimum bid with Cherry Hill Township.",
    "orlando_fl": "City-owned vacant lot published by the City of Orlando Open Data portal (including zoning, dimensions, and conforming-lot status). Confirm purchase/application eligibility with the City of Orlando.",
    "delaware_in": "Fall 2026 Delaware County / Muncie tax-sale vacant land parcel with published minimum bid (no structure improvement value). Confirm statutory redemption rules, sale terms, and bidding registration with Delaware County.",
    "millelacs_mn": "Tax-forfeited parcel marked saleable without structures in Mille Lacs County GIS. Confirm auction schedule, minimum bid, and timber/mineral terms with Mille Lacs County.",
    "ottertail_mn": "Tax-forfeited parcel published in Otter Tail County GIS. Confirm auction dates, over-the-counter availability, and deed conditions with Otter Tail County.",
    "richmond_va": "City-owned vacant surplus parcel published by the City of Richmond GIS (zero dwelling value). Confirm surplus disposition terms and RFP/application rules on rva.gov.",
    "montgomery_al": "General surplus city-owned property published in City of Montgomery GIS. Confirm availability, bid/offer procedures, and liens with the City of Montgomery.",
    "waterloo_ia": "Commercial/industrial property for sale published in City of Waterloo GIS. Confirm pricing, TIF/incentive eligibility, and zoning directly with the City of Waterloo.",
    "wyandotte_ks": "Vacant parcel held by the Unified Government of Wyandotte County / Kansas City, KS Land Bank. Confirm application criteria, side-lot or development pricing, and covenants on wycokck.org.",
    "shawnee_ks": "County-owned vacant parcel published for sale in Shawnee County GIS with listed sale price. Confirm special assessments, title terms, and purchase process on snco.gov.",
    "wilmington_de": "Land Bank side-lot parcel published by the City of Wilmington GIS. Confirm disposition eligibility, pricing, and adjacent-lot rules on wilmingtonde.gov.",
    "hartford_ct": "City-owned vacant lot published by the City of Hartford Open Data GIS. Confirm municipal disposition process, zoning, and purchase terms on hartfordct.gov.",
    "omaha_ne": "City-owned vacant land parcel published in City of Omaha / Douglas County GIS (zero buildings and zero improvement value). Confirm surplus availability and conveyance process on cityofomaha.org.",
    "bluefield_wv": "Municipal Land Bank parcel published by the City of Bluefield GIS. Confirm availability, purchase application, and development terms on bluefieldwv.gov.",
    "memphis_tn": "Surplus vacant parcel published by the City of Memphis GIS. Confirm surplus purchase eligibility, zoning, and closing terms on memphistn.gov.",
    "warwick_ri": "Vacant tax-title land parcel published in City of Warwick GIS. Confirm redemption status, tax-title auction schedule, and zoning directly with the City of Warwick.",
    "boston_ma": "City-owned parcel under the care and custody of the City of Boston Mayor's Office of Housing (MOH). Confirm RFP/disposition availability and development guidelines on boston.gov.",
    "albany_wy": "Vacant land parcel on the Albany County, Wyoming 2026 Tax Sale list (unimproved land where land value equals total assessed value). Confirm redemption cutoff, tax certificate rules, and auction schedule on albanycountywy.gov.",
    "odot_ok": "Current surplus right-of-way land published in Oklahoma DOT GIS across Oklahoma counties. Confirm sealed-bid/auction schedule, access, and quitclaim deed terms on oklahoma.gov.",
    "ms_surplus": "Unimproved parcel in the State of Mississippi Surplus GIS inventory. Confirm tax-forfeited / surplus purchase application rules and redemption status on sos.ms.gov.",
    "horry_sc": "Delinquent tax-sale parcel published by Horry County GIS with listed opening bid figure (condos/HPR units excluded). Confirm auction date, redemption period, and bidding registration on horrycountysc.gov.",
    "portland_or": "Vacant parcel held by the City of Portland (zero building area, vacant land use) in PortlandMaps Open Data. Confirm surplus disposition eligibility and zoning on portland.gov.",
    "maui_hi": "Vacant government-owned parcel in West Maui GIS (zero building value). Confirm public disposition or lease/sale availability with Maui County or Hawaii DLNR.",
    "lasvegas_nv": "Vacant city-owned real estate parcel in City of Las Vegas Open Data GIS. Confirm surplus auction or redevelopment RFP availability on lasvegasnevada.gov.",
    "peterborough_nh": "Tax-deeded land parcel held by the Town of Peterborough, New Hampshire. Confirm municipal tax-deed auction schedule and conservation restrictions on peterboroughnh.gov.",
    "yankton_sd": "Vacant city-owned lot in City of Yankton Open Data GIS (parks excluded). Confirm surplus land sale process and zoning on cityofyankton.org.",
    "burleigh_nd": "Unimproved county- or city-owned parcel in Burleigh County / Bismarck GIS (zero building market value). Confirm tax-deed sale schedule and special assessments on burleigh.gov.",
    "vcgi_vt": "Unimproved municipal parcel from Vermont Center for Geographic Information (VCGI) statewide parcel data (parks, schools, and utilities excluded). Confirm town/city tax-sale or surplus status with the local town clerk.",
    "montana_cad": "County- or city-owned vacant land parcel from the Montana State Library Statewide Cadastral Framework. Confirm county tax-deed auction availability, access, and deed terms directly with the county treasurer.",
    "boise_id": "City of Boise Housing & Community Development (COMDEV) parcel in City of Boise Open Data GIS. Confirm RFP/disposition status and zoning on cityofboise.org.",
    "auburn_me": "Unimproved municipal land parcel (undeveloped, commercial, industrial, or house-lot land) in City of Auburn GIS. Confirm tax-acquired or surplus sale status on auburnmaine.gov.",
    "portland_me": "Municipal land bank / vacant land parcel published in City of Portland, Maine GIS. Confirm surplus sale or redevelopment RFP availability on portlandmaine.gov.",
    "philly_lb": "Vacant land parcel held by the Philadelphia Land Bank in official City of Philadelphia Open Data GIS (OPA / L&I Vacant Indicators). Confirm side-lot, competitive-sale, or development application terms on phdcphila.org.",
    "cleveland_lb": "Vacant land bank parcel held by the City of Cleveland Land Bank in Cleveland Open Data GIS. Confirm side-yard, new-construction, or commercial disposition rules on clevelandohio.gov.",
    "dallas_lb": "Unimproved vacant land parcel in the City of Dallas Land Bank GIS inventory (LAND ONLY class). Confirm current lot availability, housing/development covenants, and purchase process on dallascityhall.com.",
    "milwaukee_vac": "Actively advertised City of Milwaukee Department of City Development vacant lot (Status: Acquired / Advertised / Dispose) in Milwaukee GIS. Confirm purchase price, side-lot discount, or proposal rules on city.milwaukee.gov.",
    "detroit_comm": "Actively listed City of Detroit vacant land parcel with published asking price in Detroit Open Data GIS. Confirm deed covenants, zoning, and purchase terms on detroitmi.gov.",
    "lucas_forf_2026": "Parcel on the Lucas County Auditor 2026 Forfeited Land Sale GIS roll with listed delinquent tax figure. Confirm opening bid, auction schedule, title/brownfield notes, and buyer registration on co.lucas.oh.us.",
    "sauk_wi": "Tax-forfeited parcel open for Offer to Purchase in Sauk County, Wisconsin GIS. Confirm minimum bid, easements, and county board approval rules directly with Sauk County.",
    "gis_area": "Area computed from the agency's GIS parcel outline (not a legal survey).",
}


def fact(topic, value, url, note=""):
    """url may be "=" (the listing's own page), "@key" (a URLS entry) or "@outline" (computed from the listing)."""
    f = {"topic": topic, "value": str(value), "url": url}
    if note:
        f["note"] = note
    return f


def note_text(note):
    return NOTES.get(note, note)


URLS = {}  # filled below, once the source constants exist


def expand_url(listing, url):
    if url == "=":
        return listing["url"]
    if url == "@outline":
        return outline_url(listing)
    if url.startswith("@"):
        return URLS.get(url[1:], "")
    return url


def outline_url(listing):
    if listing["source"] == "st-louis-lra":
        return one_parcel_url(STL_GIS, "ParcelId='%s'" % listing["apn"])
    if listing["source"] == "arkansas-cosl":
        return one_parcel_url(AR_GIS, "UPPER(county)='%s' AND parcelid='%s'" % (listing["county"].upper().replace("'", "''"),
                                                                              listing["apn"].replace("'", "''")))
    if listing["source"] == "alaska-trust-otc":
        return one_parcel_url(TRUST_GIS, "FILENUMBER='%s'" % listing["id"].split("-", 1)[1])
    if listing["source"] == "louisville-landbank":
        return one_parcel_url(LOU_GIS, "Parcel_No_='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "lucas-county-oh":
        return one_parcel_url(LUCAS_GIS, "parid='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "la-county-ttc":
        return one_parcel_url(LA_TTC_2026B if listing["id"].startswith("ca-la26b-") else LA_TTC_2026A,
                              "APN='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "broward-surplus":
        return one_parcel_url(BROWARD_GIS, "FOLIO='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "utah-udot":
        return one_parcel_url(UDOT_GIS, "parcel_number='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "albany-landbank":
        return one_parcel_url(ALBANY_GIS, "PIN_SBL='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "las-cruces-nm":
        return one_parcel_url(LASCRUCES_GIS, "ACCOUNTNUM='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "baltimore-vacant":
        return one_parcel_url(BALTIMORE_GIS, "PIN='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "big-spring-tx":
        return one_parcel_url(BIGSPRING_GIS, "prop_id_te='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "king-county-wa":
        return one_parcel_url(KING_WA_GIS, "PIN='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "charlotte-nc":
        return one_parcel_url(CHARLOTTE_GIS, "ParcelID='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "canton-ga":
        return one_parcel_url(CANTON_GA_GIS, "PIN='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "san-miguel-co":
        return one_parcel_url(SANMIGUEL_CO_GIS, "PIN='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "navajo-county-az":
        return one_parcel_url(NAVAJO_AZ_GIS, "APN='%s'" % listing["apn"].replace("'", "''"))
    if listing["source"] == "cherry-hill-nj":
        return one_parcel_url(CHERRYHILL_NJ_GIS, "UNIQUEID='%s'" % listing["apn"].replace("'", "''"))
    return ""


def rings_acres(rings):
    """Approximate geodesic area in acres for WGS84 lon/lat polygon rings (outer minus holes)."""
    if not rings:
        return None
    R = 6378137.0
    total_m2 = 0.0
    for idx, ring in enumerate(rings):
        if len(ring) < 3:
            continue
        lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
        cos_lat = math.cos(lat0)
        xs = [math.radians(p[0]) * R * cos_lat for p in ring]
        ys = [math.radians(p[1]) * R for p in ring]
        a = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(zip(xs, ys), list(zip(xs, ys))[1:] + [(xs[0], ys[0])]))) / 2.0
        total_m2 += a if idx == 0 else -a
    ac = abs(total_m2) / 4046.8564224
    return round(ac, 4) if ac > 0.001 else None


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def ring_centroid(ring):
    """Area-weighted centroid of a closed lon/lat ring; falls back to the vertex mean."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-14:
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    return (cx / (3 * a), cy / (3 * a))


def ring_area(ring):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))) / 2.0


def simplify(rings, max_points=240):
    out = []
    for ring in rings:
        pts = [(round(p[0], 6), round(p[1], 6)) for p in ring]
        if len(pts) > max_points:
            step = len(pts) / float(max_points)
            pts = [pts[int(i * step)] for i in range(max_points)] + [pts[0]]
        out.append(pts)
    return out


def apply_geometry(listing, rings, source_url, source_name):
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return
    main = max(rings, key=ring_area)
    lon, lat = ring_centroid(main)
    if not (-180 <= lon <= -60 and 15 <= lat <= 72):
        return
    listing["lat"], listing["lon"] = round(lat, 6), round(lon, 6)
    listing["geometry"] = simplify(rings)
    listing["facts"].append(fact("parcel_outline", "Outline from the %s GIS, matched by parcel number" % source_name, "@outline", "outline"))


def one_parcel_url(endpoint, where):
    """A short query URL for one parcel's outline, so a reader can check it."""
    return endpoint + "?" + urllib.parse.urlencode({"f": "json", "where": where, "outFields": "*", "outSR": "4326",
                                                    "returnGeometry": "true"})


def arcgis_query(fetch, endpoint, where, fields):
    q = urllib.parse.urlencode({"f": "json", "where": where, "outFields": fields, "outSR": "4326",
                                "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500"})
    url = endpoint + "?" + q
    data = fetch.json(url)
    if not isinstance(data, dict) or "features" not in data:
        raise FetchError("unexpected ArcGIS answer from %s" % endpoint)
    return url, data["features"]


def quote_list(values):
    return ",".join("'%s'" % v.replace("'", "''") for v in values)


# ------------------------------------------------------------------------------------------- St. Louis

STL = "https://static.stlouis-mo.gov/open-data/SLDC/REAL-ESTATE/"
STL_GIS = "https://maps8.stlouis-mo.gov/arcgis/rest/services/SLDC/SLDC_Real_Estate/MapServer/0/query"
STL_DETAIL = "https://www.stlouis-mo.gov/government/property/city-owned-property-search.cfm?action=detail&parcelId=%s"
STL_SIDE_LOT_POLICY = "https://www.lrastl.org/s/Side-Lot-Program-323.pdf"


def parse_st_louis(available_csv, inventory_csv, warn, side_lot_price=None):
    available = list(csv.DictReader(io.StringIO(available_csv)))
    inventory = list(csv.DictReader(io.StringIO(inventory_csv)))
    if not available or not inventory or "Parcel_Status" not in inventory[0] or "ParcelId" not in available[0]:
        raise StructureError("St. Louis inventory columns changed")
    status = {}
    for r in inventory:
        pid = r["ParcelId"]
        status[pid] = "Conflict" if pid in status and status[pid] != r["Parcel_Status"] else r["Parcel_Status"]
    unique, conflicts = {}, set()
    for r in available:
        prior = unique.get(r["ParcelId"])
        if prior and any(clean(prior.get(k)) != clean(r.get(k)) for k in ("Address", "SQFT", "Usage", "PropertyType")):
            conflicts.add(r["ParcelId"])
        else:
            unique[r["ParcelId"]] = r
    if conflicts:
        warn("skipped %d St. Louis parcel IDs listed twice with different facts" % len(conflicts))
    source_of = {r["ParcelId"]: clean(r.get("Property_Source")) for r in inventory}
    out = []
    for pid, r in unique.items():
        if pid in conflicts or status.get(pid) != "Available" or r.get("PropertyType") != "Lot":
            continue
        if clean(r.get("Usage")).lower() != "vacant lot":
            continue
        if not re.match(r"^\d{11}$", pid) or not clean(r.get("Address")):
            continue
        sqft = number(r.get("SQFT"))
        url = STL_DETAIL % pid
        eligible = clean(r.get("Side lot Eligible?")).lower() == "yes" and sqft and sqft < 4000
        price = side_lot_price if eligible else None
        facts = [
            fact("availability", "Available", "@stl_inventory",
                 "stl_available"),
            fact("lot_area", "%s square feet" % ("{:,}".format(int(sqft)) if sqft else "not listed"),
                 "@stl_available", "stl_area"),
            (fact("price", "$%s through the Side Lot Program" % "{:,.0f}".format(price), STL_SIDE_LOT_POLICY,
                  "Eligible adjacent purchasers only. Application and recording fees are separate.")
             if price else fact("price", "No asking price in the city's export", "@stl_available", "stl_price")),
        ]
        if clean(r.get("NeighborhoodName")):
            facts.append(fact("neighborhood", clean(r["NeighborhoodName"]), "="))
        if clean(r.get("WARD")):
            facts.append(fact("ward", clean(r["WARD"]), "="))
        if clean(r.get("Side lot Eligible?")):
            facts.append(fact("side_lot_eligible", clean(r["Side lot Eligible?"]), "=", "stl_side_lot"))
        if clean(r.get("Irregular_Lot")):
            facts.append(fact("irregular_lot", clean(r["Irregular_Lot"]), "="))
        if source_of.get(pid):
            facts.append(fact("how_the_city_acquired_it", source_of[pid], "@stl_inventory"))
        out.append({
            "id": "stl-%s" % pid, "source": "st-louis-lra", "title": "%s, St. Louis (vacant lot)" % clean(r["Address"]).title(),
            "state": "MO", "county": "St. Louis city", "locality": "St. Louis", "apn": pid,
            "acres": round(sqft / 43560.0, 4) if sqft else None, "price": price, "price_kind": "application" if price else "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": url, "address": clean(r["Address"]).title(),
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "application required"],
        })
    return out


def st_louis(fetch, now, warn):
    side_lot_price = None
    try:
        policy = pdf_text(fetch, STL_SIDE_LOT_POLICY, extraction_mode="plain")
        m = re.search(r"Property Purchase Price\s+\$([\d,]+(?:\.\d{2})?)", policy)
        if "SIDE LOT PROGRAM" in policy and m:
            side_lot_price = number(m[1])
        else:
            warn("St. Louis's Side Lot price was not stated in the expected policy format")
    except (FetchError, StructureError) as error:
        warn("St. Louis Side Lot prices unavailable (%s)" % error)
    rows = parse_st_louis(fetch.text(STL + "LRA_INVENTORY_AVAILABLE.csv"),
                         fetch.text(STL + "LRA_INVENTORY.csv"), warn, side_lot_price)

    if len(rows) < 100:
        raise StructureError("only %d St. Louis vacant lots: the export looks incomplete" % len(rows))
    by_apn = {r["apn"]: r for r in rows}
    ids = sorted(by_apn)
    failed = 0
    for i in range(0, len(ids), 150):
        chunk = ids[i:i + 150]
        try:
            url, feats = arcgis_query(fetch, STL_GIS, "ParcelId IN (%s)" % quote_list(chunk), "ParcelId")
        except FetchError as exc:
            failed += 1
            if failed > 5:
                warn("St. Louis parcel outlines stopped after repeated failures (%s)" % exc)
                break
            continue
        for f in feats:
            pid = str((f.get("attributes") or {}).get("ParcelId") or "")
            if pid in by_apn and f.get("geometry", {}).get("rings"):
                apply_geometry(by_apn[pid], f["geometry"]["rings"], one_parcel_url(STL_GIS, "ParcelId='%s'" % pid), "City of St. Louis")
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Arkansas

AR = "https://auction.cosl.org"
AR_GIS = "https://gis.arkansas.gov/arcgis/rest/services/FEATURESERVICES/Planning_Cadastre/MapServer/6/query"
TOKEN = re.compile(r"^[A-Za-z0-9_-]{10,150}$")


def central_time(text):
    """Arkansas feed times are local Central time without an offset. Read them as CST (UTC-6), as the original
    did: conservative for deadlines (never earlier than the true cutoff)."""
    if not text:
        return None
    t = str(text).strip()
    t = re.sub(r"(\.\d{6})\d+", r"\1", t)
    if re.search(r"(Z|[+-]\d\d:\d\d)$", t):
        t = t.replace("Z", "+00:00")
    else:
        t += "-06:00"
    try:
        return datetime.datetime.fromisoformat(t).astimezone(datetime.timezone.utc)
    except ValueError:
        return None


def parse_arkansas_rows(data):
    if not isinstance(data, dict) or not isinstance(data.get("Data"), list) or not isinstance(data.get("Total"), int) or data.get("Errors"):
        raise StructureError("Arkansas feed structure changed")
    rows = []
    for r in data["Data"]:
        if not isinstance(r.get("CoSLPropertyId"), int) or not TOKEN.match(str(r.get("ListingToken") or "")):
            raise StructureError("Arkansas listing identity changed")
        rows.append(r)
    return rows, data["Total"]


def arkansas_listing(r, now):
    apn, county = clean(r.get("CoSLParcelNumber")), clean(r.get("CoSLCountyName")).title()
    url = "%s/Auction/Listing/%s" % (AR, r["ListingToken"])
    start, end = central_time(r.get("Start")), central_time(r.get("End"))
    if end and end < now:
        status = "auction_closed"
    elif end:
        status = "auction_open"
    else:
        status = "auction_terms"
    acres = number(r.get("Acreage"))
    bid = number(r.get("StartingBid"))
    facts = [
        fact("minimum_bid", "$%s" % "{:,.2f}".format(bid) if bid else "not stated", "=", "ar_bid"),
        fact("acreage", "%s acres" % ("%g" % acres) if acres else "not stated by the source", "="),
        fact("parcel_number", apn, "=", "ar_apn"),
    ]
    if r.get("Section") or r.get("Township") or r.get("Range"):
        facts.append(fact("section_township_range", "S%s T%s R%s" % (clean(str(r.get("Section") or "")), clean(str(r.get("Township") or "")),
                                                                     clean(str(r.get("Range") or ""))), "="))
    facts.append(fact("auction_window", "Starts: %s; ends: %s" % (
        start.strftime("%Y-%m-%d %H:%M UTC") if start else "with the first bid (see terms)",
        end.strftime("%Y-%m-%d %H:%M UTC") if end else "not set"), "=", "ar_window"))
    bids = r.get("NumberOfBids") or 0
    if bids:
        facts.append(fact("bids", "%d bid%s, current bid $%s" % (bids, "" if bids == 1 else "s", "{:,.2f}".format(float(r.get("CurrentBid") or 0))), "="))
    added = str(r.get("Added") or "")[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", added):
        facts.append(fact("added_to_auction_list", added, "="))
    return {
        "id": "ar-%s" % r["CoSLPropertyId"], "source": "arkansas-cosl",
        "title": "%s County parcel %s (Arkansas tax-sale land)" % (county, apn),
        "state": "AR", "county": county, "locality": "", "apn": apn, "acres": acres, "price": bid,
        "price_kind": "min_bid" if bid else "none", "offering": "auction", "status": status,
        "deadline": end.strftime("%Y-%m-%dT%H:%M:%SZ") if end else None, "url": url, "address": "",
        "lat": None, "lon": None, "geometry": None, "facts": facts,
        "tags": ["tax-forfeited parcel", "auction terms apply", "improvements unverified"],
        "listed_date": added if re.match(r"^\d{4}-\d{2}-\d{2}$", added) else None,
        "rotating_url": True,   # COSL issues a new token per read; old tokens keep working (checked 2026-11-22)
    }


def arkansas(fetch, now, warn):
    rows, total, page = {}, None, 1
    while True:
        data, upstream = parse_arkansas_rows(fetch.json("%s/auctions/grid_read?page=%d&pageSize=500" % (AR, page)))
        if total is None:
            total = upstream
        elif upstream != total:
            warn("the Arkansas inventory changed during paging (%d then %d)" % (total, upstream))
        before = len(rows)
        for r in data:
            rows[r["CoSLPropertyId"]] = r
        if len(rows) >= total or not data or len(rows) == before:
            break
        page += 1
        if page > 40:
            warn("Arkansas paging stopped at 40 pages")
            break
    complete = len(rows) >= (total or 0)
    if not complete:
        warn("read %d of %d Arkansas parcels" % (len(rows), total))
    listings = [arkansas_listing(r, now) for r in rows.values()]
    by_county = {}
    for l in listings:
        if l["apn"] and l["county"]:
            by_county.setdefault(l["county"].upper(), []).append(l)
    failed = 0
    for county, ls in sorted(by_county.items()):
        index = {l["apn"]: l for l in ls}
        apns = sorted(index)
        for i in range(0, len(apns), 60):
            chunk = apns[i:i + 60]
            try:
                url, feats = arcgis_query(fetch, AR_GIS, "UPPER(county)='%s' AND parcelid IN (%s)" % (county.replace("'", "''"), quote_list(chunk)),
                                          "parcelid,county,adrlabel,adrcity")
            except FetchError as exc:
                failed += 1
                if failed > 8:
                    warn("Arkansas parcel outlines stopped after repeated failures (%s)" % exc)
                    return listings, {"complete": complete, "upstream_total": total}
                continue
            for f in feats:
                a = f.get("attributes") or {}
                l = index.get(str(a.get("parcelid") or ""))
                if l and f.get("geometry", {}).get("rings") and l["lat"] is None:
                    apply_geometry(l, f["geometry"]["rings"], one_parcel_url(
                        AR_GIS, "UPPER(county)='%s' AND parcelid='%s'" % (county.replace("'", "''"), l["apn"].replace("'", "''"))),
                        "Arkansas GIS Office")
                    if a.get("adrlabel"):
                        l["address"] = clean(a["adrlabel"]).title()
                    if a.get("adrcity"):
                        l["locality"] = clean(a["adrcity"]).title()
    return listings, {"complete": complete, "upstream_total": total}


# ------------------------------------------------------------------------------------------- Wisconsin

WI = "https://bcpl.wisconsin.gov/Pages/SurplusBCPLProperty.aspx"


def parse_wisconsin(page, now, warn):
    deadline = None
    m = re.search(r"auction closing of ([A-Z][a-z]+ \d{1,2}, \d{4})", clean(page))
    if m:
        try:
            d = datetime.datetime.strptime(m.group(1), "%B %d, %Y")
            deadline = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=datetime.timezone(datetime.timedelta(hours=-6)))
        except ValueError:
            deadline = None
    marks = [(m.start(), "auction") for m in re.finditer(r"<h2[^>]*>[^<]*Sealed Bid Auction", page)]
    marks += [(m.start(), "private") for m in re.finditer(r"<h2[^>]*>[^<]*Private Sale", page)]
    marks.sort()
    starts = [m for m in re.finditer(r'<div class="surplus-land-container(?:-evenrow)?"([^>]*)>', page)]
    out = []
    for i, m in enumerate(starts):
        if re.search(r"display\s*(?::|&#58;)\s*none", m.group(1), re.I):
            continue
        chunk = page[m.start(): starts[i + 1].start() if i + 1 < len(starts) else m.start() + 20000]
        program = None
        for pos, prog in marks:
            if pos < m.start():
                program = prog
        if not program:
            continue
        get = lambda cls: clean((re.search(r'<div class="%s"[^>]*>(.*?)</div>' % cls, chunk, re.S) or [None, ""])[1])  # noqa: E731
        county = re.sub(r"\s+County$", "", get("surplus-land-header1"), flags=re.I)
        name, file_no = get("surplus-land-header2"), get("surplus-land-header3")
        if not re.match(r"^[ST]\d+[A-Z0-9-]*$", file_no, re.I) or not name or "[" in name:
            continue
        cols = re.findall(r'<div class="surplus-land-column[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        tax = re.sub(r"^Tax Parcel ID:\s*", "", clean(cols[0]) if cols else "", flags=re.I)
        desc = clean(cols[1]) if len(cols) > 1 else ""
        money = clean(cols[2]) if len(cols) > 2 else ""
        pdf = re.search(r'href="([^"]+\.pdf)"', chunk, re.I)
        if re.search(r"\bSOLD\b", money, re.I):
            continue
        price = number((re.search(r"\$[\d,]+(?:\.\d+)?", money) or [None])[0])
        if re.search(r"SALE PENDING", money, re.I):
            status = "pending"
        elif program == "private":
            status = "listed"
        else:
            status = "auction_closed" if deadline and now > deadline else "auction_open"
        area = re.search(r"(?:This\s+|Approximately\s+|consists of approximately\s+)([\d,.]+)[ -]acres?\b", desc, re.I)
        acres = number(area.group(1)) if area else None
        facts = [fact("file_number", file_no, WI), fact("tax_parcel_id", tax or "not listed", WI),
                 fact("sale_program", "Sealed-bid auction" if program == "auction" else "Private sale (first qualified buyer)", WI),
                 fact("minimum_bid" if program == "auction" else "price", "$%s" % "{:,.0f}".format(price) if price else "not listed", WI,
                      "Board of Commissioners of Public Lands figure. Confirm terms in the sale documents.")]
        if re.search(r"no legal access|landlocked", desc, re.I):
            facts.append(fact("access", "The agency describes the land as having no legal access", WI,
                              "Landlocked land needs an easement or a neighbour's permission to reach it."))
        if acres:
            facts.append(fact("acreage", "%g acres (as stated in the description)" % acres, WI))
        if desc:
            facts.append(fact("agency_description_excerpt", (desc[:220] + "\u2026") if len(desc) > 220 else desc, WI,
                              "Short excerpt of the agency's description; the full text and map are on the agency page."))
        if pdf:
            facts.append(fact("agency_map", "Parcel map (PDF)", urllib.parse.urljoin(WI, html.unescape(pdf.group(1)))))
        if deadline and program == "auction":
            facts.append(fact("bid_deadline", deadline.strftime("%B %d, %Y"), WI, "Auction closing date stated on the agency page."))
        out.append({
            "id": "wi-%s" % slug(file_no), "source": "wisconsin-bcpl", "title": "%s, %s County, Wisconsin (%s)" % (name, county, file_no),
            "state": "WI", "county": county, "locality": "", "apn": tax, "acres": acres, "price": price,
            "price_kind": ("min_bid" if program == "auction" else "cash") if price else "none",
            "offering": "auction" if program == "auction" else "sale", "status": status,
            "deadline": deadline.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if deadline and program == "auction" else None,
            "url": WI, "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["state trust land", "sealed bid" if program == "auction" else "private sale"],
        })
    if not starts:
        raise StructureError("Wisconsin BCPL page structure changed: no property rows")
    return out


def wisconsin(fetch, now, warn):
    return parse_wisconsin(fetch.text(WI), now, warn), {"complete": True}


# ------------------------------------------------------------------------------------------- Alaska Trust

TRUST = "https://alaskamentalhealthtrust.org/otc-parcel/"
TRUST_GIS = "https://services1.arcgis.com/7HDiw78fcUiM2BWn/arcgis/rest/services/OTC_Website_Parcel_List_Join/FeatureServer/0/query"


def parse_trust(page, warn):
    out = []
    for block in re.split(r'<div class="left-side">', page)[1:]:
        block = block.split('<div class="right-side">')[0]
        title = clean((re.search(r'<h1 class="main-heading">(.*?)</h1>', block, re.S) or [None, ""])[1])
        if not title.startswith("OTC:"):
            continue
        text = clean(block)
        field = lambda label: (re.search(r"%s:\s*(.*?)(?=\s+[A-Z][A-Za-z ]+:|\s+Learn More|$)" % label, text) or [None, ""])[1].strip()  # noqa: E731
        mht = field("MHT Number")
        price = number(field("Purchase Price"))
        acres = number(field("Acres"))
        href = (re.search(r'<a href="([^"]+)" class="button-submit"', block) or [None, ""])[1]
        if not mht or not href or price is None or acres is None:
            warn("skipped an incomplete Alaska Trust card: %s" % title[:60])
            continue
        url = urllib.parse.urljoin(TRUST, html.unescape(href))
        if urllib.parse.urlsplit(url).netloc != "alaskamentalhealthtrust.org":
            continue
        road = field("Road Access")
        facts = [fact("price", "$%s" % "{:,.0f}".format(price), url, "Fixed over-the-counter purchase price set by the Trust Land Office."),
                 fact("acreage", "%g acres" % acres, url), fact("trust_parcel_number", "MHT %s" % mht, url),
                 fact("availability", "Listed in the over-the-counter sale catalog", TRUST,
                      "Confirm the parcel is still available and how to apply with the Trust Land Office.")]
        if road:
            facts.append(fact("road_access", road, url, "access_attr"))
        loc, sub = field("Location"), field("Subdivision")
        out.append({
            "id": "akmht-%s" % mht, "source": "alaska-trust-otc",
            "title": re.sub(r"\s*\*NEW\*$", "", title[4:].strip()), "state": "AK", "county": "", "locality": loc,
            "apn": "", "acres": acres, "price": price, "price_kind": "cash", "offering": "sale", "status": "listed",
            "deadline": None, "url": url, "address": sub, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["state trust land", "fixed price", "no road access reported" if road.lower() == "no" else "check access"],
            "_mht": mht,
        })
    if not out and "main-heading" not in page:
        raise StructureError("Alaska Trust catalog structure changed")
    return out


def alaska_trust(fetch, now, warn):
    rows = parse_trust(fetch.text(TRUST), warn)
    if rows:
        try:
            url, feats = arcgis_query(fetch, TRUST_GIS, "FILENUMBER IN (%s)" % quote_list([r["_mht"] for r in rows]), "FILENUMBER")
            by = {r["_mht"]: r for r in rows}
            for f in feats:
                r = by.get(str((f.get("attributes") or {}).get("FILENUMBER") or ""))
                if r and f.get("geometry", {}).get("rings"):
                    apply_geometry(r, f["geometry"]["rings"], one_parcel_url(TRUST_GIS, "FILENUMBER='%s'" % r["_mht"]), "Trust Land Office")
        except FetchError as exc:
            warn("Alaska Trust parcel outlines unavailable (%s)" % exc)
    for r in rows:
        r.pop("_mht", None)
    return rows, {"complete": True}


# ------------------------------------------------------------------------------------------- Alaska DNR

DNR = "https://dnr.alaska.gov/mlw/landsales/"


def parse_dnr(page, home, now, warn):
    deadlines = {}
    for m in re.finditer(r"bidding period for (?:Agricultural )?Auction #(\d+) is between .{1,60}? and ([A-Z][a-z]+ \d{1,2}, \d{4})", clean(home)):
        try:
            d = datetime.datetime.strptime(m.group(2), "%B %d, %Y")
            deadlines[m.group(1)] = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=datetime.timezone(datetime.timedelta(hours=-9)))
        except ValueError:
            pass
    cards = list(re.finditer(r'<section class="card js-parcel-card"([^>]*)>(.*?)</section>', page, re.S))
    if not cards:
        raise StructureError("Alaska DNR parcel cards not found")
    out = []
    for m in cards:
        attrs = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', m.group(1)))
        number_ = "%s-%s" % (attrs.get("auction", ""), attrs.get("parcel", ""))
        if not re.match(r"^\d+-\d+$", number_):
            continue
        body = clean(m.group(2))
        url = DNR + "parcels/details/%s" % number_
        auction = "minimum bid" in body.lower()
        price, acres = number(attrs.get("price")), number(attrs.get("acres"))
        program = attrs.get("program", "")
        dl = deadlines.get(attrs.get("auction", ""))
        if auction:
            status = "auction_closed" if dl and now > dl else "auction_open"
        else:
            status = "listed"
        sub = html.unescape(attrs.get("subd", "")).strip()
        facts = [fact("dnr_parcel", number_, url, "Alaska DNR offering number, not a borough assessor number."),
                 fact("program", program or "not stated", url)]
        if price:
            facts.append(fact("minimum_bid" if auction else "price", "$%s" % "{:,.0f}".format(price), url))
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, url))
        for key, label in (("road-access", "road_access"), ("water-access", "water_access"), ("remote-access", "remote_access"),
                           ("resident-requirement", "alaska_residents_only"), ("region", "region")):
            if attrs.get(key):
                facts.append(fact(label, attrs[key], url))
        if attrs.get("adl"):
            facts.append(fact("case_file", "ADL %s" % attrs["adl"], url))
        if dl and auction:
            facts.append(fact("bid_deadline", dl.strftime("%B %d, %Y"), DNR, "Read from the DNR land sales page; confirm the exact cutoff."))
        out.append({
            "id": "akdnr-%s" % number_, "source": "alaska-dnr", "title": "%s, Alaska (DNR parcel %s)" % (sub or "Alaska state land", number_),
            "state": "AK", "county": "", "locality": html.unescape(attrs.get("region", "")), "apn": "", "acres": acres,
            "price": price, "price_kind": ("min_bid" if auction else "cash") if price else "none",
            "offering": "auction" if auction else "sale", "status": status,
            "deadline": dl.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dl and auction else None,
            "url": url, "address": sub, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["state land", program or "sale", "no road access reported" if attrs.get("road-access") == "no" else "check access"],
        })
    return out


def alaska_dnr(fetch, now, warn):
    page = fetch.text(DNR + "parcels/")
    try:
        home = fetch.text(DNR)
    except FetchError:
        home = ""
    return parse_dnr(page, home, now, warn), {"complete": True}


# ------------------------------------------------------------------------------------------- Detroit Land Bank (MI)

DLBA_GIS = "https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/DLBA_Owned_Properties/FeatureServer/0/query"
DLBA_URL = "https://buildingdetroit.org/properties"
DLBA_NEIGHBORHOOD_URL = "https://buildingdetroit.org/sidelots/index/neighborhood/"
DLBA_NEIGHBORHOOD = "Neighborhood Lot For Sale"
DLBA_PROGRAMS = (
    DLBA_NEIGHBORHOOD,
    "Marketed Lot For Sale",
    "Oversized Lot For Sale",
    "Auction Lot For Sale",
    "Own It Now Lot For Sale",
    "Create-a-Project For Sale",
)


def parse_detroit_features(features, warn, neighborhood_price=None):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("parcel_id") or "")).rstrip(".")
        addr = clean(str(a.get("name") or ""))
        prog = clean(str(a.get("inventory_status_socrata") or ""))
        if not pid or prog not in DLBA_PROGRAMS:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        lat = a.get("latitude")
        lon = a.get("longitude")
        geom = f.get("geometry") or {}
        if lat is None and geom.get("y") is not None:
            lat = geom.get("y")
        if lon is None and geom.get("x") is not None:
            lon = geom.get("x")
        try:
            lat = round(float(lat), 6) if lat is not None else None
            lon = round(float(lon), 6) if lon is not None else None
            if lat is not None and lon is not None and not (-85 <= lon <= -81 and 41 <= lat <= 44):
                lat = lon = None
        except (TypeError, ValueError):
            lat = lon = None
        is_auction = "auction" in prog.lower()
        neighborhood_lot = prog == DLBA_NEIGHBORHOOD
        price = neighborhood_price if neighborhood_lot else None
        source_url = DLBA_NEIGHBORHOOD_URL if neighborhood_lot else DLBA_URL
        place = addr.title() if addr else "Parcel " + pid
        facts = [
            fact("sale_program", prog, "@dlba_gis", "dlba_program"),
            fact("parcel_number", pid, DLBA_URL),
        ]
        if neighborhood_lot:
            facts.append(fact("eligibility", "Nearby residents who meet the Detroit Land Bank program requirements may apply.", source_url))
        if price is not None:
            facts.append(fact("price", "$%g per eligible Neighborhood Lot" % price, source_url))
        else:
            facts.append(fact("price", "See Detroit Land Bank program terms", source_url, "dlba_price"))
        if clean(str(a.get("neighborhood") or "")):
            facts.append(fact("neighborhood", clean(str(a["neighborhood"])), "@dlba_gis"))
        if a.get("council_district") is not None and str(a.get("council_district")).strip():
            facts.append(fact("council_district", "District %s" % clean(str(a["council_district"])), "@dlba_gis"))
        out.append({
            "id": "mi-dlba-%s" % slug(pid), "source": "detroit-dlba",
            "title": "%s, Detroit (%s)" % (place, prog.lower()),
            "state": "MI", "county": "Wayne", "locality": "Detroit", "apn": pid,
            "acres": None, "price": price, "price_kind": "application" if price is not None else "none",
            "offering": "auction" if is_auction else "sale",
            "status": "auction_terms" if is_auction else "listed",
            "deadline": None, "url": source_url, "address": addr.title(),
            "lat": lat, "lon": lon, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", prog.lower(), "application required"],
        })
    return out


def parse_detroit_neighborhood_price(page):
    text = clean(page)
    match = re.search(r"Neighborhood Lots will be sold for \$([\d,]+(?:\.\d{2})?)\b", text, re.I)
    return number(match[1]) if match else None


def detroit_dlba(fetch, now, warn):
    where = "inventory_status_socrata IN (%s)" % quote_list(DLBA_PROGRAMS)
    fields = "parcel_id,name,inventory_status_socrata,neighborhood,council_district,latitude,longitude"
    count = fetch.json(DLBA_GIS + "?" + urllib.parse.urlencode({
        "f": "json", "where": where, "returnCountOnly": "true"
    })).get("count")
    if not isinstance(count, int) or not 50 <= count <= 100000:
        raise StructureError("Detroit Land Bank marketed lot count is outside the supported range")
    try:
        price = parse_detroit_neighborhood_price(fetch.text(DLBA_NEIGHBORHOOD_URL))
    except FetchError:
        price = None
    if price is None:
        warn("Detroit Neighborhood Lot program price unavailable; published without a price")

    rows, seen, offset = [], set(), 0
    while offset < count:
        q = urllib.parse.urlencode({
            "f": "json", "where": where, "outFields": fields,
            "returnGeometry": "false", "orderByFields": "ObjectId ASC",
            "resultRecordCount": 2000, "resultOffset": offset,
        })
        data = fetch.json(DLBA_GIS + "?" + q)
        if not isinstance(data, dict) or "features" not in data:
            raise StructureError("Detroit Land Bank ArcGIS response changed")
        features = data["features"]
        if not features:
            break
        offset += len(features)
        additions = [row for row in parse_detroit_features(features, warn, price) if row["id"] not in seen]
        if not additions:
            break
        rows.extend(additions)
        seen.update(row["id"] for row in additions)
    if len(rows) < 50:
        raise StructureError("only %d Detroit Land Bank marketed lots: feed looks incomplete" % len(rows))
    if offset != count:
        warn("Detroit Land Bank returned %d of %d queried lots" % (offset, count))
    return rows, {"complete": offset == count, "upstream_total": count}


# ------------------------------------------------------------------------------------------- Kansas City Land Bank (MO)

KC_API = "https://data.kcmo.org/resource/2ebw-sp7f.json"
KC_PORTAL = "https://kclandbank.org/"
KC_DATASET = "https://data.kcmo.org/Neighborhoods/Land-Bank-and-Kansas-City-Missouri-Homesteading-Au/2ebw-sp7f"


def parse_kc_rows(raw_rows, warn):
    out, seen = [], set()
    for r in raw_rows:
        pid = clean(str(r.get("parcel_number") or ""))
        addr = clean(str(r.get("address") or ""))
        status_raw = clean(str(r.get("property_status") or ""))
        inv_raw = clean(str(r.get("inventory_type") or ""))
        pclass = clean(str(r.get("property_class") or ""))
        if not pid or not addr:
            continue
        if status_raw.lower() != "acquired" or inv_raw.lower() != "land bank" or "vacant" not in pclass.lower():
            continue
        if pid in seen:
            continue
        seen.add(pid)
        county = clean(str(r.get("county") or "Jackson")).title()
        sqft = number(r.get("square_footage"))
        acres = round(sqft / 43560.0, 4) if sqft else None
        loc = r.get("location_1") if isinstance(r.get("location_1"), dict) else {}
        lat = lon = None
        try:
            if loc.get("latitude") is not None and loc.get("longitude") is not None:
                la, lo = float(loc["latitude"]), float(loc["longitude"])
                if 38.5 <= la <= 39.6 and -95.0 <= lo <= -94.0:
                    lat, lon = round(la, 6), round(lo, 6)
        except (TypeError, ValueError):
            lat = lon = None
        acq = str(r.get("date_of_acquisition") or "")[:10]
        facts = [
            fact("availability", "Acquired (Land Bank inventory)", "@kc_dataset", "kc_available"),
            fact("parcel_number", pid, "@kc_dataset"),
            fact("price", "Application-based (no list price published)", KC_PORTAL, "kc_price"),
        ]
        if sqft:
            facts.append(fact("lot_area", "%s square feet" % "{:,}".format(int(round(sqft))), "@kc_dataset", "stl_area"))
        if pclass:
            facts.append(fact("property_class", pclass, "@kc_dataset"))
        if clean(str(r.get("zoned_as") or "")):
            facts.append(fact("zoning", clean(str(r["zoned_as"])), "@kc_dataset"))
        if clean(str(r.get("neighborhood") or "")):
            facts.append(fact("neighborhood", clean(str(r["neighborhood"])), "@kc_dataset"))
        if clean(str(r.get("school_district") or "")):
            facts.append(fact("school_district", clean(str(r["school_district"])), "@kc_dataset"))
        if clean(str(r.get("city_council_district") or "")):
            facts.append(fact("council_district", clean(str(r["city_council_district"])), "@kc_dataset"))
        if re.match(r"^\d{4}-\d{2}-\d{2}$", acq):
            facts.append(fact("acquired_date", acq, "@kc_dataset"))
        out.append({
            "id": "kc-%s" % slug(pid), "source": "kansas-city-landbank",
            "title": "%s, Kansas City (vacant lot)" % addr.title(),
            "state": "MO", "county": county, "locality": "Kansas City", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": KC_PORTAL, "address": addr.title(),
            "lat": lat, "lon": lon, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "application required", pclass.lower()],
        })
    return out


def kansas_city_landbank(fetch, now, warn):
    where = "property_status='Acquired' AND upper(inventory_type)='LAND BANK' AND upper(property_class) like '%VACANT%'"
    all_raw, offset, limit = [], 0, 1000
    complete = True
    for _ in range(15):
        q = urllib.parse.urlencode({"$where": where, "$limit": str(limit), "$offset": str(offset), "$order": "parcel_number"})
        batch = fetch.json(KC_API + "?" + q)
        if not isinstance(batch, list):
            raise StructureError("Kansas City Land Bank Socrata API structure changed")
        all_raw.extend(batch)
        if len(batch) < limit:
            break
        offset += len(batch)
    else:
        complete = False
        warn("Kansas City Land Bank pagination reached safety limit")
    rows = parse_kc_rows(all_raw, warn)
    if len(rows) < 100:
        raise StructureError("only %d Kansas City Land Bank vacant lots: feed looks incomplete" % len(rows))
    return rows, {"complete": complete, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- California DGS

CA_DGS = "https://www.dgs.ca.gov/RESD/Projects/Page-Content/Projects-List-Folder/State-Commercial-Opportunities-Portal"


def parse_california_dgs(page, now, warn):
    out, seen = [], set()
    for li in re.findall(r"(?is)<li[^>]*>(.*?)</li>", page):
        text = clean(li)
        m = re.match(r"^(.{3,200}?)\s*[-–—]\s*Proposal Deadline\s+([A-Z][a-z]+ \d{1,2}, \d{4})\s*$", text)
        if not m:
            continue
        title = clean(m.group(1))
        try:
            d = datetime.datetime.strptime(m.group(2), "%B %d, %Y")
            dl = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=datetime.timezone(datetime.timedelta(hours=-8)))
        except ValueError:
            continue
        site_m = re.search(r"Site ID\s*#?([A-Z0-9-]+)", title, re.I)
        site_id = site_m.group(1) if site_m else slug(title)[:40]
        lid = "ca-dgs-%s" % slug(site_id)
        if lid in seen:
            continue
        seen.add(lid)
        county = "Los Angeles" if re.search(r"Los Angeles", title, re.I) else ("Riverside" if re.search(r"Norco", title, re.I) else "")
        locality = "Los Angeles" if re.search(r"Los Angeles", title, re.I) else ("Norco" if re.search(r"Norco", title, re.I) else "")
        closed = now > dl
        facts = [
            fact("proposal_deadline", dl.strftime("%B %d, %Y"), CA_DGS, "ca_proposal"),
            fact("sale_program", "State Commercial / Surplus Development Opportunity (RFP)", CA_DGS),
        ]
        if site_m:
            facts.append(fact("agency_site_id", site_m.group(1), CA_DGS))
        out.append({
            "id": lid, "source": "california-dgs",
            "title": "%s (California DGS)" % title,
            "state": "CA", "county": county, "locality": locality, "apn": site_m.group(1) if site_m else "",
            "acres": None, "price": None, "price_kind": "none", "offering": "proposal",
            "status": "auction_closed" if closed else "proposal_open",
            "deadline": dl.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "url": CA_DGS, "address": title, "lat": None, "lon": None, "geometry": None,
            "facts": facts, "tags": ["state surplus notice", "development proposal"],
        })
    if not out:
        raise StructureError("California DGS page has no recognizable proposal deadlines")
    return out


def california_dgs(fetch, now, warn):
    return parse_california_dgs(fetch.text(CA_DGS), now, warn), {"complete": True}


# ------------------------------------------------------------------------------------------- Chicago City-Owned Land (IL)

CHI_API = "https://data.cityofchicago.org/resource/aksk-kvfp.json"
CHI_URL = "https://www.chicago.gov/city/en/sites/block-builder/home.html"
CHI_DATASET = "https://data.cityofchicago.org/Community-Economic-Development/City-Owned-Land-Inventory/aksk-kvfp"


def parse_chicago_rows(raw_rows, now, warn):
    out, seen = [], set()
    for r in raw_rows:
        rid = clean(str(r.get("id") or ""))
        pin = clean(str(r.get("pin") or ""))
        addr = clean(str(r.get("address") or ""))
        pstatus = clean(str(r.get("property_status") or ""))
        sstatus = clean(str(r.get("sales_status") or ""))
        if not addr or pstatus.lower() != "owned by city" or sstatus not in ("Apply", "Offered"):
            continue
        key = pin or rid
        if not key or key in seen:
            continue
        seen.add(key)
        sqft = number(r.get("sq_ft")) or number(r.get("square_footage_city_estimate"))
        acres = round(sqft / 43560.0, 4) if sqft else None
        lat = lon = None
        try:
            if r.get("latitude") is not None and r.get("longitude") is not None:
                la, lo = float(r["latitude"]), float(r["longitude"])
                if 41.5 <= la <= 42.1 and -88.1 <= lo <= -87.4:
                    lat, lon = round(la, 6), round(lo, 6)
        except (TypeError, ValueError):
            lat = lon = None
        app_url_raw = r.get("application_url")
        if isinstance(app_url_raw, dict):
            app_url_raw = app_url_raw.get("url")
        url = str(app_url_raw or "").strip()
        if not (url.startswith("https://www.chicago.gov/") or url.startswith("https://chicago.gov/")):
            url = CHI_URL
        dl = None
        if sstatus == "Apply" and r.get("application_deadline"):
            dl_dt = central_time(str(r["application_deadline"])[:10] + "T23:59:59")
            if dl_dt:
                dl = dl_dt
        if sstatus == "Apply":
            status = "auction_closed" if (dl and now > dl) else "proposal_open"
            offering = "proposal"
        else:
            status = "listed"
            offering = "sale"
        facts = [
            fact("sale_program", "ChiBlockBuilder — %s%s" % (
                sstatus, (" (%s)" % clean(r.get("offer_round"))) if clean(r.get("offer_round")) else ""), "@chi_dataset", "chi_program"),
            fact("parcel_number", pin or rid, "@chi_dataset"),
            fact("price", "Set by city program / application review (no asking price published)", url, "chi_program"),
        ]
        if sqft:
            facts.append(fact("lot_area", "%s square feet" % "{:,}".format(int(round(sqft))), "@chi_dataset", "stl_area"))
        if clean(r.get("zoning_classification")):
            facts.append(fact("zoning", clean(r["zoning_classification"]), "@chi_dataset"))
        if clean(r.get("community_area_name")):
            facts.append(fact("neighborhood", clean(r["community_area_name"]).title(), "@chi_dataset"))
        if clean(r.get("ward")):
            facts.append(fact("ward", clean(r["ward"]), "@chi_dataset"))
        val = number(r.get("land_value"))
        if val:
            facts.append(fact("city_valuation", "$%s" % "{:,.0f}".format(val), "@chi_dataset", "chi_val"))
        if dl:
            facts.append(fact("proposal_deadline", dl.strftime("%B %d, %Y"), url))
        acq = str(r.get("date_of_acquisition") or "")[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", acq):
            facts.append(fact("acquired_date", acq, "@chi_dataset"))
        tags = ["city-owned vacant lot", "application required"]
        if sstatus == "Apply":
            tags.append("open application round")
        if clean(r.get("zoning_classification")):
            tags.append("zoned %s" % clean(r["zoning_classification"]))
        out.append({
            "id": "il-chi-%s" % slug(rid or pin), "source": "chicago-dpd",
            "title": "%s, Chicago (city-owned lot)" % addr.title(),
            "state": "IL", "county": "Cook", "locality": "Chicago", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": offering,
            "status": status, "deadline": dl.strftime("%Y-%m-%dT%H:%M:%SZ") if dl else None,
            "url": url, "address": addr.title(), "lat": lat, "lon": lon, "geometry": None,
            "facts": facts, "tags": tags,
        })
    return out


def chicago_dpd(fetch, now, warn):
    where = "property_status='Owned by City' AND sales_status IN ('Apply','Offered')"
    all_raw, offset, limit = [], 0, 1000
    complete = True
    for _ in range(10):
        q = urllib.parse.urlencode({"$where": where, "$limit": str(limit), "$offset": str(offset), "$order": "id"})
        batch = fetch.json(CHI_API + "?" + q)
        if not isinstance(batch, list):
            raise StructureError("Chicago City-Owned Land API structure changed")
        all_raw.extend(batch)
        if len(batch) < limit:
            break
        offset += len(batch)
    else:
        complete = False
        warn("Chicago pagination reached safety limit")
    rows = parse_chicago_rows(all_raw, now, warn)
    if len(rows) < 50:
        raise StructureError("only %d Chicago lots: feed looks incomplete" % len(rows))
    return rows, {"complete": complete, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Pittsburgh Vacant Land (PA)

PGH_API = "https://data.wprdc.org/api/3/action/datastore_search"
PGH_RES = "e1dcee82-9179-4306-8167-5891915b62a7"
PGH_URL = "https://pghlandbank.org/"
PGH_DATASET = "https://data.wprdc.org/datastore/dump/" + PGH_RES


def parse_pittsburgh_rows(records, warn):
    out, seen = [], set()
    for r in records:
        pin = clean(str(r.get("pin") or ""))
        rid = clean(str(r.get("id") or ""))
        addr = clean(str(r.get("address") or ""))
        cls = clean(str(r.get("class") or ""))
        cur = clean(str(r.get("current_status") or ""))
        inv = clean(str(r.get("inventory_type") or ""))
        if not pin or not addr:
            continue
        if cls.lower() != "vacant land" or cur.lower() != "available for sale" or inv.lower() != "public sale":
            continue
        if pin in seen:
            continue
        seen.add(pin)
        sqft = number(r.get("parc_sq_ft"))
        acres = round(sqft / 43560.0, 4) if sqft else None
        lat = lon = None
        try:
            if r.get("latitude") is not None and r.get("longitude") is not None:
                la, lo = float(r["latitude"]), float(r["longitude"])
                if 40.2 <= la <= 40.7 and -80.3 <= lo <= -79.7:
                    lat, lon = round(la, 6), round(lo, 6)
        except (TypeError, ValueError):
            lat = lon = None
        facts = [
            fact("availability", "Available for Sale (Public Sale)", "@pgh_dataset", "pgh_avail"),
            fact("parcel_number", pin, "@pgh_dataset"),
            fact("price", "Application / sale review (no asking price published)", PGH_URL, "pgh_avail"),
        ]
        if sqft:
            facts.append(fact("lot_area", "%s square feet" % "{:,}".format(int(round(sqft))), "@pgh_dataset", "stl_area"))
        if clean(str(r.get("zoned_as") or "")):
            facts.append(fact("zoning", clean(str(r["zoned_as"])), "@pgh_dataset"))
        if clean(str(r.get("neighborhood_name") or "")):
            facts.append(fact("neighborhood", clean(str(r["neighborhood_name"])), "@pgh_dataset"))
        if clean(str(r.get("ward") or "")):
            facts.append(fact("ward", clean(str(r["ward"])), "@pgh_dataset"))
        if clean(str(r.get("council_district") or "")):
            facts.append(fact("council_district", "District %s" % clean(str(r["council_district"])), "@pgh_dataset"))
        if clean(str(r.get("acquisition_method") or "")):
            facts.append(fact("how_the_city_acquired_it", clean(str(r["acquisition_method"])), "@pgh_dataset"))
        acq = str(r.get("acquisition_date") or "")[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", acq):
            facts.append(fact("acquired_date", acq, "@pgh_dataset"))
        out.append({
            "id": "pa-pgh-%s" % slug(rid or pin), "source": "pittsburgh-vacant",
            "title": "%s, Pittsburgh (vacant land)" % addr.title(),
            "state": "PA", "county": "Allegheny", "locality": "Pittsburgh", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": PGH_URL, "address": addr.title(),
            "lat": lat, "lon": lon, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "public sale inventory", "application required"],
        })
    return out


def pittsburgh_vacant(fetch, now, warn):
    filt = json.dumps({"class": "Vacant Land", "current_status": "Available for Sale", "inventory_type": "Public Sale"})
    all_raw, offset, limit = [], 0, 1000
    complete, total = True, None
    for _ in range(10):
        q = urllib.parse.urlencode({"resource_id": PGH_RES, "filters": filt, "limit": str(limit), "offset": str(offset)})
        data = fetch.json(PGH_API + "?" + q)
        if not isinstance(data, dict) or not data.get("success") or not isinstance((data.get("result") or {}).get("records"), list):
            raise StructureError("Pittsburgh WPRDC datastore API changed")
        res = data["result"]
        if total is None:
            total = res.get("total")
        batch = res["records"]
        all_raw.extend(batch)
        if len(batch) < limit or (total is not None and len(all_raw) >= total):
            break
        offset += len(batch)
    else:
        complete = False
        warn("Pittsburgh pagination reached safety limit")
    rows = parse_pittsburgh_rows(all_raw, warn)
    if len(rows) < 100:
        raise StructureError("only %d Pittsburgh vacant parcels: feed looks incomplete" % len(rows))
    return rows, {"complete": complete, "upstream_total": total or len(rows)}


# ------------------------------------------------------------------------------------------- Louisville Metro Landbank (KY)

LOU_GIS = "https://services1.arcgis.com/79kfd2K6fskCAkyg/arcgis/rest/services/LandbankInventoryParcels/FeatureServer/0/query"
LOU_URL = "https://data.louisvilleky.gov/"
LOU_DISPOSITION = ("https://louisvilleky.gov/sites/default/files/2025-08/"
                   "Landbank%20Disposition%20Program%20Policies%20%E2%80%93%20Updated%20June%202025.pdf")


def parse_louisville_features(features, warn, side_yard_price=None):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("Parcel_No_") or ""))
        addr = clean(str(a.get("Street_Add") or ""))
        pstatus = clean(str(a.get("Property_S") or ""))
        itype = clean(str(a.get("Inventory_") or ""))
        if not pid or not addr or pstatus.lower() != "available" or itype.lower() != "lot":
            continue
        if pid in seen:
            continue
        seen.add(pid)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings)
        buildable = clean(str(a.get("Buildable_") or ""))
        category = clean(str(a.get("Category") or ""))
        side_yard = (category.lower() == "available - unbuildable lot" and buildable.lower() == "no"
                     and acres and acres * 43560 <= 4000)
        price = side_yard_price if side_yard else None
        facts = [
            fact("availability", "Available — Landbank Lot", "@lou_gis", "lou_avail"),
            fact("parcel_number", pid, "@lou_gis"),
            (fact("price", "$%s through My New Side Yard" % "{:,.0f}".format(price), LOU_DISPOSITION,
                  "Available to eligible applicants with a qualifying adjacent structure. Confirm terms with the Landbank.")
             if price else fact("price", "Program-specific pricing via Louisville Metro Landbank", LOU_URL, "lou_avail")),
        ]
        if buildable:
            facts.append(fact("buildable_lot", buildable, "@lou_gis"))
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, "@lou_gis", "gis_area"))
        if category:
            facts.append(fact("sale_program", category, "@lou_gis"))
        if a.get("Council_Di") is not None and str(a.get("Council_Di")).strip():
            facts.append(fact("council_district", "District %s" % clean(str(a["Council_Di"])), "@lou_gis"))
        row = {
            "id": "ky-lou-%s" % slug(pid), "source": "louisville-landbank",
            "title": "%s, Louisville (landbank lot)" % addr.title(),
            "state": "KY", "county": "Jefferson", "locality": "Louisville", "apn": pid,
            "acres": acres, "price": price, "price_kind": "application" if price else "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": LOU_URL, "address": addr.title(),
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "application required"] + (["buildable lot"] if buildable.lower() == "yes" else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(LOU_GIS, "Parcel_No_='%s'" % pid.replace("'", "''")), "Louisville Metro / LOJIC")
        out.append(row)
    return out


def louisville_landbank(fetch, now, warn):
    where = "Property_S='Available' AND Inventory_='Lot'"
    fields = "Parcel_No_,Street_Add,Postal_Cod,Property_S,Inventory_,Council_Di,Buildable_,Category"
    all_feats, offset, page_size = [], 0, 500
    complete = True
    for _ in range(10):
        q = urllib.parse.urlencode({
            "f": "json", "where": where, "outFields": fields, "outSR": "4326",
            "returnGeometry": "true", "geometryPrecision": "6",
            "resultRecordCount": str(page_size), "resultOffset": str(offset),
        })
        data = fetch.json(LOU_GIS + "?" + q)
        if not isinstance(data, dict) or "features" not in data:
            raise StructureError("Louisville Landbank ArcGIS response changed")
        feats = data["features"]
        all_feats.extend(feats)
        if not data.get("exceededTransferLimit") or len(feats) < page_size:
            break
        offset += len(feats)
    else:
        complete = False
        warn("Louisville pagination reached safety limit")
    side_yard_price = None
    try:
        policy = pdf_text(fetch, LOU_DISPOSITION)
        yard = re.search(r"Program Name\s+My New Side Yard(.*?)(?:B\.\s+Lot On My Block|$)", policy, re.S)
        m = re.search(r"(?m)^\s*Cost\s+\$([\d,]+\.\d{2})", yard[1]) if yard else None
        if m and "Vacant lots up to 4,000 square feet" in yard[1]:
            side_yard_price = number(m[1])
        else:
            warn("Louisville's Side Yard price or parcel eligibility changed")
    except (FetchError, StructureError) as error:
        warn("Louisville Side Yard prices unavailable (%s)" % error)
    rows = parse_louisville_features(all_feats, warn, side_yard_price)
    if len(rows) < 50:
        raise StructureError("only %d Louisville landbank lots: feed looks incomplete" % len(rows))
    return rows, {"complete": complete, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Lucas County Land Bank (OH)

LUCAS_GIS = "https://services3.arcgis.com/T8dczfwPixv79EgZ/arcgis/rest/services/Land_Bank/FeatureServer/0/query"
LUCAS_URL = "https://lucascountylandbank.org/"
LUCAS_VACANT_LUCS = ("500", "501", "400", "401", "640")


def parse_lucas_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("parid") or a.get("assessor_num") or ""))
        addr_raw = clean(str(a.get("property_address") or ""))
        luc = clean(str(a.get("luc") or ""))
        if not pid or not addr_raw or luc not in LUCAS_VACANT_LUCS:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        street = addr_raw.split(",")[0].strip()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("acreage_calc")) or number(a.get("acreage")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        zoning = clean(str(a.get("zoning") or ""))
        legal = clean(str(a.get("legal_description") or ""))
        facts = [
            fact("availability", "Lucas County Land Bank vacant land inventory", "@lucas_gis", "lucas_avail"),
            fact("parcel_number", pid, "@lucas_gis"),
            fact("price", "Application / program pricing via Lucas County Land Bank", LUCAS_URL, "lucas_avail"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, "@lucas_gis"))
        if zoning:
            facts.append(fact("zoning", zoning, "@lucas_gis"))
        if legal:
            facts.append(fact("legal_description", legal[:200], "@lucas_gis"))
        if a.get("taxyr"):
            facts.append(fact("tax_year", str(a["taxyr"]), "@lucas_gis"))
        row = {
            "id": "oh-lucas-%s" % slug(pid), "source": "lucas-county-oh",
            "title": "%s, Toledo (Lucas County Land Bank lot)" % street.title(),
            "state": "OH", "county": "Lucas", "locality": "Toledo", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": LUCAS_URL, "address": street.title(),
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "application required"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(LUCAS_GIS, "parid='%s'" % pid.replace("'", "''")), "Lucas County GIS")
        out.append(row)
    return out


def lucas_county_oh(fetch, now, warn):
    where = "luc IN (%s)" % quote_list(LUCAS_VACANT_LUCS)
    fields = "parid,assessor_num,property_address,zoning,acreage,acreage_calc,legal_description,luc,taxyr"
    all_feats, offset, page_size = [], 0, 500
    complete = True
    for _ in range(10):
        q = urllib.parse.urlencode({
            "f": "json", "where": where, "outFields": fields, "outSR": "4326",
            "returnGeometry": "true", "geometryPrecision": "6",
            "resultRecordCount": str(page_size), "resultOffset": str(offset),
        })
        data = fetch.json(LUCAS_GIS + "?" + q)
        if not isinstance(data, dict) or "features" not in data:
            raise StructureError("Lucas County Land Bank ArcGIS response changed")
        feats = data["features"]
        all_feats.extend(feats)
        if not data.get("exceededTransferLimit") or len(feats) < page_size:
            break
        offset += len(feats)
    else:
        complete = False
        warn("Lucas County pagination reached safety limit")
    rows = parse_lucas_features(all_feats, warn)
    if len(rows) < 50:
        raise StructureError("only %d Lucas County vacant lots: feed looks incomplete" % len(rows))
    return rows, {"complete": complete, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- LA County TTC Tax Auctions (CA)

LA_TTC_2026B = "https://services1.arcgis.com/yobXtsY8IPR6NpgV/arcgis/rest/services/TTC_Auction_2026B/FeatureServer/0/query"
LA_TTC_2026A = "https://services1.arcgis.com/yobXtsY8IPR6NpgV/arcgis/rest/services/TTC_Auction_2026_A/FeatureServer/0/query"
LA_TTC_URL = "https://ttc.lacounty.gov/auction-general-information/"


def parse_la_ttc_features(features, series, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        apn = clean(str(a.get("APN") or a.get("AIN") or ""))
        if not apn or apn in seen:
            continue
        if series == "2026B":
            addr_tag = clean(str(a.get("AUC_ADDR") or ""))
            if "vacant" not in addr_tag.lower():
                continue
            bid = number(a.get("AUC_MINBID"))
            item = clean(str(a.get("AUC_ITEM") or ""))
            city = clean(str(a.get("TaxRateCit") or a.get("SitusCity") or "")).title()
            legal = clean(str(a.get("AUC_LEGAL") or ""))
            zoning = clean(str(a.get("UseType") or ""))
            acres = None
            id_prefix = "ca-la26b-"
        else:
            if clean(str(a.get("LANDUSE") or "")).lower() != "vacant":
                continue
            bid = number(a.get("MIN_BID"))
            item = clean(str(a.get("ITEM") or ""))
            city = clean(str(a.get("SITE_CITY") or "")).title()
            legal = clean(str(a.get("LEGAL_DESC") or a.get("LEGAL") or ""))
            zoning = clean(str(a.get("ZONING") or a.get("ZONETYPE") or ""))
            acres = number(a.get("ACRES")) or (round(number(a.get("SQFOOT")) / 43560.0, 4) if number(a.get("SQFOOT")) else None)
            id_prefix = "ca-la26a-"
        seen.add(apn)
        rings = (f.get("geometry") or {}).get("rings") or []
        if not acres and rings:
            acres = rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("sale_program", "Los Angeles County TTC Tax-Defaulted Auction %s" % series, LA_TTC_URL, "la_ttc_bid"),
            fact("minimum_bid", "$%s" % "{:,.0f}".format(bid) if bid else "not stated", LA_TTC_URL, "la_ttc_bid"),
            fact("parcel_number", apn, LA_TTC_URL),
        ]
        if item:
            facts.append(fact("auction_item", "Item #%s" % item, LA_TTC_URL))
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, LA_TTC_URL))
        if zoning:
            facts.append(fact("zoning", zoning, LA_TTC_URL))
        if legal:
            facts.append(fact("legal_description", legal[:200], LA_TTC_URL))
        loc_title = ("%s, Los Angeles County" % city) if city else "Los Angeles County"
        row = {
            "id": "%s%s" % (id_prefix, slug(apn)), "source": "la-county-ttc",
            "title": "%s parcel %s (LA County tax auction %s)" % (loc_title, apn, series),
            "state": "CA", "county": "Los Angeles", "locality": city, "apn": apn,
            "acres": acres, "price": bid, "price_kind": "min_bid" if bid else "none",
            "offering": "auction", "status": "auction_terms", "deadline": None,
            "url": LA_TTC_URL, "address": "", "lat": None, "lon": None, "geometry": None,
            "facts": facts, "tags": ["tax-defaulted parcel", "auction terms apply", "los angeles county"],
        }
        if rings:
            ep = LA_TTC_2026B if series == "2026B" else LA_TTC_2026A
            apply_geometry(row, rings, one_parcel_url(ep, "APN='%s'" % apn.replace("'", "''")), "Los Angeles County GIS")
        out.append(row)
    return out


def la_county_ttc(fetch, now, warn):
    out = []
    # Query only non-personal parcel fields (never request Owner)
    q_b = urllib.parse.urlencode({
        "f": "json", "where": "AUC_ADDR LIKE '%VACANT%'",
        "outFields": "APN,AIN,TaxRateCit,SitusCity,UseType,AUC_ITEM,AUC_MINBID,AUC_LEGAL,AUC_ADDR",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data_b = fetch.json(LA_TTC_2026B + "?" + q_b)
    if not isinstance(data_b, dict) or "features" not in data_b:
        raise StructureError("LA County TTC 2026B ArcGIS response changed")
    out.extend(parse_la_ttc_features(data_b["features"], "2026B", warn))

    q_a = urllib.parse.urlencode({
        "f": "json", "where": "LANDUSE='Vacant'",
        "outFields": "APN,AIN,SITE_CITY,ZONING,ZONETYPE,ACRES,SQFOOT,LEGAL_DESC,ITEM,MIN_BID,LANDUSE",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data_a = fetch.json(LA_TTC_2026A + "?" + q_a)
    if not isinstance(data_a, dict) or "features" not in data_a:
        raise StructureError("LA County TTC 2026A ArcGIS response changed")
    out.extend(parse_la_ttc_features(data_a["features"], "2026A", warn))
    if not out:
        raise StructureError("LA County TTC returned 0 vacant auction parcels")
    return out, {"complete": True, "upstream_total": len(out)}


# ------------------------------------------------------------------------------------------- Broward County Surplus (FL)

BROWARD_GIS = "https://services2.arcgis.com/siQBicXvlHb2Oz23/arcgis/rest/services/County_Surplus_Property/FeatureServer/0/query"
BROWARD_FOLIO_URL = "https://bcpa.net/RecInfo.asp?URL_Folio=%s"


def parse_broward_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        folio = clean(str(a.get("FOLIO") or a.get("FOLIO_NUMBER") or ""))
        if not folio or folio in seen:
            continue
        seen.add(folio)
        situs_parts = [clean(str(a.get(k) or "")) for k in ("SITUS_STREET_NUMBER", "SITUS_STREET_DIRECTION", "SITUS_STREET_NAME", "SITUS_STREET_TYPE")]
        addr = " ".join(p for p in situs_parts if p).title()
        legal = " ".join(clean(str(a.get("LEGAL_LINE_%d" % i) or "")) for i in (1, 2, 3, 4)).strip()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings)
        url = BROWARD_FOLIO_URL % urllib.parse.quote(folio, safe="")
        facts = [
            fact("sale_program", "Broward County Surplus Real Property", url, "broward_surplus"),
            fact("parcel_number", folio, url),
            fact("price", "See Broward County surplus property bidding/sale terms", url, "broward_surplus"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, url, "gis_area"))
        if legal:
            facts.append(fact("legal_description", legal[:220], url))
        if clean(str(a.get("USE_CODE") or "")):
            facts.append(fact("use_code", clean(str(a["USE_CODE"])), url))
        title_loc = addr if addr else ("Folio %s" % folio)
        row = {
            "id": "fl-broward-%s" % slug(folio), "source": "broward-surplus",
            "title": "%s, Broward County (surplus parcel)" % title_loc,
            "state": "FL", "county": "Broward", "locality": "", "apn": folio,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": url, "address": addr,
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["county surplus parcel", "florida"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(BROWARD_GIS, "FOLIO='%s'" % folio.replace("'", "''")), "Broward County GIS")
        out.append(row)
    return out


def broward_surplus(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "FOLIO,FOLIO_NUMBER,LEGAL_LINE_1,LEGAL_LINE_2,LEGAL_LINE_3,LEGAL_LINE_4,USE_CODE,SITUS_STREET_NUMBER,SITUS_STREET_DIRECTION,SITUS_STREET_NAME,SITUS_STREET_TYPE,SITUS_CITY,SITUS_ZIP_CODE",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(BROWARD_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Broward County Surplus ArcGIS response changed")
    rows = parse_broward_features(data["features"], warn)
    if len(rows) < 5:
        raise StructureError("only %d Broward surplus parcels: feed looks incomplete" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Utah DOT Surplus Property (UT)

UDOT_GIS = "https://services.arcgis.com/pA2nEVnB6tquxgOW/arcgis/rest/services/UDOT_Right_of_Way_Surplus_Parcels/FeatureServer/0/query"
UDOT_URL = "https://connect.udot.utah.gov/business/surplus-property/"


def parse_udot_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if a.get("sell_entry_number") or a.get("void_date"):
            continue
        pnum = clean(str(a.get("parcel_number") or a.get("parcel_id") or ""))
        tax_id = clean(str(a.get("tax_id") or ""))
        key = tax_id or pnum
        if not key or key in seen:
            continue
        seen.add(key)
        county = clean(str(a.get("county") or "")).title()
        city = clean(str(a.get("city") or "")).title()
        addr = clean(str(a.get("situs_address") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings)
        if not acres:
            epm = number(a.get("acreage_epm"))
            if epm:
                # UDOT stores sq ft in acreage_epm when > 100, or acres when small
                acres = round(epm / 43560.0, 4) if epm > 200 else round(epm, 4)
        facts = [
            fact("sale_program", "UDOT Surplus Right-of-Way Property", UDOT_URL, "udot_surplus"),
            fact("parcel_number", pnum or tax_id, UDOT_URL),
            fact("price", "Appraisal / auction pricing set by UDOT Right of Way", UDOT_URL, "udot_surplus"),
        ]
        if tax_id:
            facts.append(fact("tax_parcel_id", tax_id, UDOT_URL))
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, UDOT_URL, "gis_area"))
        if a.get("section") or a.get("township") or a.get("range_"):
            facts.append(fact("section_township_range", "S%s %s %s" % (
                clean(str(a.get("section") or "")), clean(str(a.get("township") or "")), clean(str(a.get("range_") or ""))), UDOT_URL))
        if clean(str(a.get("pin_description") or "")):
            facts.append(fact("agency_description_excerpt", clean(str(a["pin_description"]))[:220], UDOT_URL))
        loc = addr or (city if city else (county + " County" if county else "Utah"))
        row = {
            "id": "ut-udot-%s" % slug(key), "source": "utah-udot",
            "title": "%s, %s (UDOT surplus parcel %s)" % (loc, county + " County" if county else "Utah", pnum or key),
            "state": "UT", "county": county, "locality": city, "apn": pnum or tax_id,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": UDOT_URL, "address": addr,
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["state surplus parcel", "utah dot"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(UDOT_GIS, "parcel_number='%s'" % (pnum or key).replace("'", "''")), "Utah DOT GIS")
        elif a.get("latitude") and a.get("longitude"):
            try:
                la, lo = float(a["latitude"]), float(a["longitude"])
                if 36.5 <= la <= 42.5 and -114.5 <= lo <= -108.5:
                    row["lat"], row["lon"] = round(la, 6), round(lo, 6)
            except (TypeError, ValueError):
                pass
        out.append(row)
    return out


def utah_udot(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "sell_entry_number IS NULL AND void_date IS NULL",
        "outFields": "parcel_number,parcel_id,tax_id,pin_description,township,range_,section,latitude,longitude,acreage_epm,county,city,situs_address,sell_entry_number,void_date",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(UDOT_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Utah DOT Surplus ArcGIS response changed")
    rows = parse_udot_features(data["features"], warn)
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Albany County Land Bank (NY)

ALBANY_GIS = "https://services6.arcgis.com/JJzptGyn7EDStgyp/arcgis/rest/services/Tax_Parcel_Dataset_for_Public_View/FeatureServer/5/query"
ALBANY_URL = "https://www.albanycountylandbank.org/"


def parse_albany_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("PIN_SBL") or a.get("print_key") or ""))
        addr = clean(str(a.get("full_addre") or ""))
        pclass = clean(str(a.get("prop_class") or ""))
        if not pin or not pclass.startswith("3"):
            continue
        if pin in seen:
            continue
        seen.add(pin)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("acres")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        zoning = clean(str(a.get("rezone1") or ""))
        zdesc = clean(str(a.get("rezone1des") or ""))
        cdesc = clean(str(a.get("class_desc") or "Vacant Land"))
        facts = [
            fact("availability", "Albany County Land Bank — %s" % cdesc, ALBANY_URL, "albany_lb"),
            fact("parcel_number", clean(str(a.get("print_key") or pin)), ALBANY_URL),
            fact("price", "Application / program pricing on albanycountylandbank.org", ALBANY_URL, "albany_lb"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, ALBANY_URL))
        if zoning:
            facts.append(fact("zoning", ("%s (%s)" % (zoning, zdesc)) if zdesc else zoning, ALBANY_URL))
        if cdesc:
            facts.append(fact("property_class", cdesc, ALBANY_URL))
        title_loc = addr.title() if addr else ("Parcel %s" % clean(str(a.get("print_key") or pin)))
        row = {
            "id": "ny-alb-%s" % slug(pin), "source": "albany-landbank",
            "title": "%s, Albany County (land bank vacant lot)" % title_loc,
            "state": "NY", "county": "Albany", "locality": "Albany", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": ALBANY_URL, "address": addr.title(),
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "new york", "application required"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(ALBANY_GIS, "PIN_SBL='%s'" % pin.replace("'", "''")), "Albany County GIS")
        out.append(row)
    return out


def albany_landbank(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "prop_class LIKE '3%'",
        "outFields": "PIN_SBL,print_key,full_addre,prop_class,class_desc,acres,rezone1,rezone1des",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "1000",
    })
    data = fetch.json(ALBANY_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Albany County Land Bank ArcGIS response changed")
    rows = parse_albany_features(data["features"], warn)
    if len(rows) < 25:
        raise StructureError("only %d Albany Land Bank lots: feed looks incomplete" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Orange County Tax Deed Auctions (FL)

ORANGE_FL_GIS = "https://services1.arcgis.com/0U8EQ1FrumPeIqDb/arcgis/rest/services/Tax_Sale_Data/FeatureServer/0/query"
ORANGE_FL_URL = "https://www.orangecountyfl.net/"
ORANGE_FL_PA = "https://ocpaweb.ocpafl.org/"


def parse_orange_fl_features(features, now, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        tda = clean(str(a.get("USER_TDA_NUM") or ""))
        parcel = clean(str(a.get("USER_PARCEL") or ""))
        dstat = clean(str(a.get("USER_Deed_Status") or ""))
        sdate = clean(str(a.get("USER_Sale_Date") or ""))
        if not tda or not parcel or dstat.lower() != "active sale":
            continue
        if tda in seen:
            continue
        seen.add(tda)
        dl = None
        if re.match(r"^\d{2}/\d{2}/\d{4}$", sdate):
            try:
                d = datetime.datetime.strptime(sdate, "%m/%d/%Y")
                dl = datetime.datetime(d.year, d.month, d.day, 15, 0, 0, tzinfo=datetime.timezone.utc)
            except ValueError:
                dl = None
        status = "auction_closed" if (dl and now > dl) else ("auction_open" if dl else "auction_terms")
        geom = f.get("geometry") or {}
        lat = lon = None
        try:
            if geom.get("y") is not None and geom.get("x") is not None:
                la, lo = float(geom["y"]), float(geom["x"])
                if 28.0 <= la <= 29.0 and -82.0 <= lo <= -80.8:
                    lat, lon = round(la, 6), round(lo, 6)
        except (TypeError, ValueError):
            lat = lon = None
        facts = [
            fact("sale_program", "Orange County Tax Deed Sale (%s)" % dstat, ORANGE_FL_URL, "orange_fl_tda"),
            fact("auction_item", "TDA #%s" % tda, ORANGE_FL_URL),
            fact("parcel_number", parcel, ORANGE_FL_PA),
            fact("price", "Opening bid set by Orange County Comptroller prior to auction", ORANGE_FL_URL, "orange_fl_tda"),
        ]
        if dl:
            facts.append(fact("bid_deadline", dl.strftime("%B %d, %Y"), ORANGE_FL_URL, "Scheduled tax deed auction date; confirm status and cutoff with the county."))
        out.append({
            "id": "fl-ora-%s" % slug(tda), "source": "orange-county-fl",
            "title": "Orange County parcel %s (Tax Deed Sale %s)" % (parcel, tda),
            "state": "FL", "county": "Orange", "locality": "Orlando", "apn": parcel,
            "acres": None, "price": None, "price_kind": "none", "offering": "auction",
            "status": status, "deadline": dl.strftime("%Y-%m-%dT%H:%M:%SZ") if dl else None,
            "url": ORANGE_FL_URL, "address": "", "lat": lat, "lon": lon, "geometry": None,
            "facts": facts, "tags": ["tax deed sale", "florida", "auction terms apply"],
        })
    return out


def orange_county_fl(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "USER_Deed_Status='Active Sale'",
        "outFields": "USER_TDA_NUM,USER_Sale_Date,USER_Deed_Status,USER_PARCEL",
        "outSR": "4326", "returnGeometry": "true", "resultRecordCount": "500",
    })
    data = fetch.json(ORANGE_FL_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Orange County FL Tax Sale ArcGIS response changed")
    rows = parse_orange_fl_features(data["features"], now, warn)
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- City of Las Cruces Vacant Land (NM)

LASCRUCES_GIS = "https://services1.arcgis.com/ejcbAsQEUUGWEyzb/arcgis/rest/services/City_Owned_Vacant_Land/FeatureServer/15/query"
LASCRUCES_URL = "https://lascruces.gov/"


def parse_lascruces_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        acct = clean(str(a.get("ACCOUNTNUM") or a.get("MAPCODE") or ""))
        if not acct or acct in seen:
            continue
        seen.add(acct)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("TOTALACRES")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City-Owned Vacant Land Inventory", LASCRUCES_URL, "lascruces_vac"),
            fact("parcel_number", acct, LASCRUCES_URL),
            fact("price", "Inquiry / surplus disposition via City of Las Cruces", LASCRUCES_URL, "lascruces_vac"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, LASCRUCES_URL))
        if clean(str(a.get("MAPCODE") or "")):
            facts.append(fact("tax_parcel_id", clean(str(a["MAPCODE"])), LASCRUCES_URL))
        if a.get("CouncilDistrict") is not None and str(a.get("CouncilDistrict")).strip():
            facts.append(fact("council_district", "District %s" % clean(str(a["CouncilDistrict"])), LASCRUCES_URL))
        row = {
            "id": "nm-lc-%s" % slug(acct), "source": "las-cruces-nm",
            "title": "Las Cruces city-owned vacant parcel %s" % acct,
            "state": "NM", "county": "Doña Ana", "locality": "Las Cruces", "apn": acct,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": LASCRUCES_URL, "address": "",
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "new mexico"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(LASCRUCES_GIS, "ACCOUNTNUM='%s'" % acct.replace("'", "''")), "City of Las Cruces GIS")
        out.append(row)
    return out


def las_cruces_nm(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "ACCOUNTNUM,MAPCODE,TOTALACRES,TOTALSQFT,CouncilDistrict,Zip_Code,Commercial_Residential",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(LASCRUCES_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Las Cruces Vacant Land ArcGIS response changed")
    rows = parse_lascruces_features(data["features"], warn)
    if len(rows) < 5:
        raise StructureError("only %d Las Cruces vacant parcels: feed looks incomplete" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Baltimore City Vacant Properties (MD)

BALTIMORE_GIS = "https://services1.arcgis.com/UWYHeuuJISiGmgXx/arcgis/rest/services/City_Owned_Vacant_Properties_in_the_DMA/FeatureServer/0/query"
BALTIMORE_URL = "https://www.baltimorecity.gov/dhcd"


def parse_baltimore_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("PIN") or a.get("BLOCKLOT") or ""))
        if not pin or pin in seen:
            continue
        seen.add(pin)
        addr = clean(str(a.get("FULLADDR") or "")).title()
        blocklot = clean(str(a.get("BLOCKLOT") or pin))
        zoning = clean(str(a.get("ZONECODE") or ""))
        lot_size = clean(str(a.get("LOT_SIZE") or ""))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings)
        facts = [
            fact("availability", "Baltimore City-Owned Vacant Inventory (DMA)", BALTIMORE_URL, "baltimore_vac"),
            fact("parcel_number", blocklot, BALTIMORE_URL),
            fact("price", "See Baltimore City DHCD disposition terms", BALTIMORE_URL, "baltimore_vac"),
        ]
        if zoning:
            facts.append(fact("zoning", zoning, BALTIMORE_URL))
        if lot_size:
            facts.append(fact("lot_area", lot_size, BALTIMORE_URL))
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, BALTIMORE_URL, "gis_area"))
        if a.get("WARD") is not None and str(a.get("WARD")).strip():
            facts.append(fact("ward", clean(str(a["WARD"])), BALTIMORE_URL))
        title_loc = addr if addr else ("Block/Lot %s" % blocklot)
        row = {
            "id": "md-bal-%s" % slug(pin), "source": "baltimore-vacant",
            "title": "%s, Baltimore (city-owned vacant parcel)" % title_loc,
            "state": "MD", "county": "Baltimore City", "locality": "Baltimore", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": BALTIMORE_URL, "address": addr,
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "maryland"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(BALTIMORE_GIS, "PIN='%s'" % pin.replace("'", "''")), "Baltimore City GIS")
        out.append(row)
    return out


def baltimore_vacant(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "PIN,BLOCKLOT,FULLADDR,ZONECODE,LOT_SIZE,WARD",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(BALTIMORE_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Baltimore Vacant Properties ArcGIS response changed")
    rows = parse_baltimore_features(data["features"], warn)
    if not rows:
        raise StructureError("Baltimore Vacant Properties returned 0 rows")
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- City of Big Spring Vacant Lots (TX)

BIGSPRING_GIS = "https://services3.arcgis.com/alxLYecgXwbvnM3O/arcgis/rest/services/City_of_Big_Spring_Owned_Property_Vacant_lots_3_2023/FeatureServer/0/query"
BIGSPRING_URL = "https://www.bigspringtx.gov/"


def parse_bigspring_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("prop_id_te") or a.get("prop_id") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        situs = " ".join(clean(str(a.get(k) or "")) for k in ("situs_num", "situs_stre")).strip()
        addr = situs.title() if situs else ""
        legal = clean(str(a.get("legal_desc") or ""))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("legal_acre")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Big Spring Vacant Lot Inventory", BIGSPRING_URL, "bigspring_tx"),
            fact("parcel_number", pid, BIGSPRING_URL),
            fact("price", "Confirm surplus bidding / purchase terms with the City of Big Spring", BIGSPRING_URL, "bigspring_tx"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, BIGSPRING_URL))
        if legal:
            facts.append(fact("legal_description", legal[:200], BIGSPRING_URL))
        title_loc = addr if addr else ("Parcel %s" % pid)
        row = {
            "id": "tx-bs-%s" % slug(pid), "source": "big-spring-tx",
            "title": "%s, Big Spring (city-owned vacant lot)" % title_loc,
            "state": "TX", "county": "Howard", "locality": "Big Spring", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": BIGSPRING_URL, "address": addr,
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "texas"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(BIGSPRING_GIS, "prop_id_te='%s'" % pid.replace("'", "''")), "Howard County / Big Spring GIS")
        out.append(row)
    return out


def big_spring_tx(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "prop_id_te,prop_id,legal_acre,legal_desc,situs_num,situs_stre,geo_id",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(BIGSPRING_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Big Spring TX Vacant Lots ArcGIS response changed")
    rows = parse_bigspring_features(data["features"], warn)
    if len(rows) < 10:
        raise StructureError("only %d Big Spring TX lots: feed looks incomplete" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- King County Tax Title (WA)

KING_WA_GIS = "https://services.arcgis.com/Ej0PsM5Aw677QF1W/arcgis/rest/services/REALPROP_AREA_1289/FeatureServer/0/query"
KING_WA_URL = "https://kingcounty.gov/"


def parse_king_wa_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("PIN") or ""))
        if not pin or pin in seen:
            continue
        if clean(str(a.get("CAT_TYPE") or "")).lower() != "tax title":
            continue
        seen.add(pin)
        addr = clean(str(a.get("ADDRESS") or "")).title()
        city = clean(str(a.get("JURISDICTIONATACQUISITION") or "")).title()
        desc = clean(str(a.get("DESCRIPTION") or ""))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACREAGE")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("sale_program", "King County Tax Title Real Property", KING_WA_URL, "king_wa"),
            fact("parcel_number", pin, KING_WA_URL),
            fact("price", "Minimum bid / direct sale price set by King County Real Estate Services", KING_WA_URL, "king_wa"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, KING_WA_URL))
        if desc:
            facts.append(fact("legal_description", desc[:200], KING_WA_URL))
        if a.get("COUNCIL_DISTRICT"):
            facts.append(fact("council_district", "District %s" % clean(str(a["COUNCIL_DISTRICT"])), KING_WA_URL))
        loc = addr or (city if city else "King County")
        row = {
            "id": "wa-king-%s" % slug(pin), "source": "king-county-wa",
            "title": "%s, %s (King County tax-title land %s)" % (loc, "King County", pin),
            "state": "WA", "county": "King", "locality": city, "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": KING_WA_URL, "address": addr,
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax-title land", "washington", "auction terms apply"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(KING_WA_GIS, "PIN='%s'" % pin.replace("'", "''")), "King County GIS")
        out.append(row)
    return out


def king_county_wa(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "CAT_TYPE='Tax Title' AND BUILDING_VALUE=0",
        "outFields": "PIN,ADDRESS,ACREAGE,DESCRIPTION,CAT_TYPE,BUILDING_VALUE,COUNCIL_DISTRICT,JURISDICTIONATACQUISITION",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(KING_WA_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("King County WA Tax Title ArcGIS response changed")
    rows = parse_king_wa_features(data["features"], warn)
    if len(rows) < 20:
        raise StructureError("only %d King County WA tax-title parcels: feed looks incomplete" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- City of Charlotte Undeveloped Land (NC)

CHARLOTTE_GIS = "https://gis.charlottenc.gov/arcgis/rest/services/ODP/City_Owned_Property/MapServer/0/query"
CHARLOTTE_URL = "https://www.charlottenc.gov/"


def parse_charlotte_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("ParcelID") or ""))
        if not pid or pid in seen:
            continue
        if clean(str(a.get("LandImprovements") or "")).lower() != "undeveloped":
            continue
        seen.add(pid)
        addr = clean(str(a.get("Address") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acres")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Charlotte Undeveloped Property Inventory", CHARLOTTE_URL, "charlotte_nc"),
            fact("parcel_number", pid, CHARLOTTE_URL),
            fact("price", "Surplus inquiry / sealed-bid terms via City of Charlotte", CHARLOTTE_URL, "charlotte_nc"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, CHARLOTTE_URL))
        title_loc = addr if addr else ("Parcel %s" % pid)
        row = {
            "id": "nc-clt-%s" % slug(pid), "source": "charlotte-nc",
            "title": "%s, Charlotte (undeveloped city land)" % title_loc,
            "state": "NC", "county": "Mecklenburg", "locality": "Charlotte", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": CHARLOTTE_URL, "address": addr,
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "north carolina"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(CHARLOTTE_GIS, "ParcelID='%s'" % pid.replace("'", "''")), "City of Charlotte GIS")
        out.append(row)
    return out


def charlotte_nc(fetch, now, warn):
    all_feats, offset, page_size = [], 0, 500
    complete = True
    for _ in range(5):
        q = urllib.parse.urlencode({
            "f": "json", "where": "LandImprovements='Undeveloped'",
            "outFields": "ParcelID,Address,Acres,LandImprovements",
            "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6",
            "resultRecordCount": str(page_size), "resultOffset": str(offset),
        })
        data = fetch.json(CHARLOTTE_GIS + "?" + q)
        if not isinstance(data, dict) or "features" not in data:
            raise StructureError("Charlotte NC ArcGIS response changed")
        feats = data["features"]
        all_feats.extend(feats)
        if not data.get("exceededTransferLimit") or len(feats) < page_size:
            break
        offset += len(feats)
    else:
        complete = False
    rows = parse_charlotte_features(all_feats, warn)
    if len(rows) < 25:
        raise StructureError("only %d Charlotte NC undeveloped parcels" % len(rows))
    return rows, {"complete": complete, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- City of Canton Land (GA)

CANTON_GA_GIS = "https://services6.arcgis.com/dpaY3zboICQILFY5/arcgis/rest/services/City_of_Canton_Owned_Property/FeatureServer/0/query"
CANTON_GA_URL = "https://www.cantonga.gov/"


def parse_canton_ga_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("PIN") or a.get("TINNoSpace") or ""))
        if not pin or pin in seen:
            continue
        seen.add(pin)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acreage")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        zoning = clean(str(a.get("Zoning") or ""))
        facts = [
            fact("availability", "City of Canton Public Property Inventory", CANTON_GA_URL, "canton_ga"),
            fact("parcel_number", pin, CANTON_GA_URL),
            fact("price", "Confirm surplus disposition terms with City of Canton", CANTON_GA_URL, "canton_ga"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, CANTON_GA_URL))
        if zoning:
            facts.append(fact("zoning", zoning, CANTON_GA_URL))
        row = {
            "id": "ga-can-%s" % slug(pin), "source": "canton-ga",
            "title": "Canton parcel %s, Cherokee County (city-owned land)" % pin,
            "state": "GA", "county": "Cherokee", "locality": "Canton", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": CANTON_GA_URL, "address": "",
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned land", "georgia"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(CANTON_GA_GIS, "PIN='%s'" % pin.replace("'", "''")), "City of Canton GIS")
        out.append(row)
    return out


def canton_ga(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "PIN,TINNoSpace,Acreage,Zoning,Subdivision",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(CANTON_GA_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Canton GA ArcGIS response changed")
    rows = parse_canton_ga_features(data["features"], warn)
    if len(rows) < 5:
        raise StructureError("only %d Canton GA parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- San Miguel County Land (CO)

SANMIGUEL_CO_GIS = "https://services.arcgis.com/aXqye4IXyXsdIpPb/arcgis/rest/services/County_Owned_Land/FeatureServer/0/query"
SANMIGUEL_CO_URL = "https://www.sanmiguelcountyco.gov/"


def parse_sanmiguel_co_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("PIN") or a.get("ACCOUNTNO") or ""))
        if not pin or pin in seen:
            continue
        seen.add(pin)
        city = clean(str(a.get("LOC_CITY") or "")).title()
        legal = clean(str(a.get("LEGAL_DESC") or ""))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings)
        facts = [
            fact("availability", "San Miguel County Owned Land Inventory", SANMIGUEL_CO_URL, "sanmiguel_co"),
            fact("parcel_number", pin, SANMIGUEL_CO_URL),
            fact("price", "Confirm surplus availability and sale method with San Miguel County", SANMIGUEL_CO_URL, "sanmiguel_co"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, SANMIGUEL_CO_URL, "gis_area"))
        if legal:
            facts.append(fact("legal_description", legal[:200], SANMIGUEL_CO_URL))
        loc = city or "San Miguel County"
        row = {
            "id": "co-sm-%s" % slug(pin), "source": "san-miguel-co",
            "title": "%s parcel %s (San Miguel County land)" % (loc, pin),
            "state": "CO", "county": "San Miguel", "locality": city, "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": SANMIGUEL_CO_URL, "address": "",
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["county land", "colorado", "mountain parcel"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(SANMIGUEL_CO_GIS, "PIN='%s'" % pin.replace("'", "''")), "San Miguel County GIS")
        out.append(row)
    return out


def san_miguel_co(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "PIN,ACCOUNTNO,LOC_CITY,LEGAL_DESC",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(SANMIGUEL_CO_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("San Miguel County CO ArcGIS response changed")
    rows = parse_sanmiguel_co_features(data["features"], warn)
    if len(rows) < 5:
        raise StructureError("only %d San Miguel County CO parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Navajo County Back Tax Auctions (AZ)

NAVAJO_AZ_GIS = "https://services.arcgis.com/cghC2lEIpJ2TRrs5/arcgis/rest/services/BackTaxAuctionProperties/FeatureServer/1/query"
NAVAJO_AZ_URL = "https://www.navajocountyaz.gov/"


def parse_navajo_az_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        apn = clean(str(a.get("APN") or ""))
        if not apn or apn in seen:
            continue
        seen.add(apn)
        auc_url = clean(str(a.get("AuctionURL") or ""))
        url = auc_url if auc_url.startswith("https://publicsurplus.com/") else NAVAJO_AZ_URL
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings)
        facts = [
            fact("sale_program", "Navajo County Back-Tax Auction Properties", url, "navajo_az"),
            fact("parcel_number", apn, url),
            fact("price", "Opening bid & auction status published on official auction page", url, "navajo_az"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, url, "gis_area"))
        row = {
            "id": "az-nav-%s" % slug(apn), "source": "navajo-county-az",
            "title": "Navajo County parcel %s (Arizona back-tax auction)" % apn,
            "state": "AZ", "county": "Navajo", "locality": "", "apn": apn,
            "acres": acres, "price": None, "price_kind": "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": url, "address": "",
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax-forfeited parcel", "arizona", "auction terms apply"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(NAVAJO_AZ_GIS, "APN='%s'" % apn.replace("'", "''")), "Navajo County GIS")
        out.append(row)
    return out


def navajo_county_az(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "APN,AuctionURL",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(NAVAJO_AZ_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Navajo County AZ ArcGIS response changed")
    rows = parse_navajo_az_features(data["features"], warn)
    if len(rows) < 10:
        raise StructureError("only %d Navajo County AZ parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- East Baton Rouge Adjudicated Land (LA)

EBR_LA_API = "https://data.brla.gov/resource/a4h4-zi7e.json"
EBR_LA_URL = "https://www.brla.gov/"


def parse_ebr_la_rows(raw_rows, warn):
    out, seen = [], set()
    for r in raw_rows:
        anum = clean(str(r.get("assessment_num") or ""))
        addr = clean(str(r.get("physadd") or "")).title()
        if not anum or anum in seen:
            continue
        seen.add(anum)
        geo = r.get("geolocation") if isinstance(r.get("geolocation"), dict) else {}
        lat = lon = None
        try:
            if geo.get("latitude") is not None and geo.get("longitude") is not None:
                la, lo = float(geo["latitude"]), float(geo["longitude"])
                if 30.2 <= la <= 30.8 and -91.4 <= lo <= -90.8:
                    lat, lon = round(la, 6), round(lo, 6)
        except (TypeError, ValueError):
            lat = lon = None
        subd = clean(str(r.get("subd") or "")).title()
        legal = clean(str(r.get("legal") or ""))
        facts = [
            fact("sale_program", "East Baton Rouge Adjudicated Tax-Sale Inventory", EBR_LA_URL, "ebr_la"),
            fact("parcel_number", anum, EBR_LA_URL),
            fact("price", "Adjudicated sale minimum bid / statutory process via East Baton Rouge Parish", EBR_LA_URL, "ebr_la"),
        ]
        if subd:
            facts.append(fact("neighborhood", subd, EBR_LA_URL))
        if legal:
            facts.append(fact("legal_description", legal[:200], EBR_LA_URL))
        if r.get("tax_roll_year"):
            facts.append(fact("tax_year", clean(str(r["tax_roll_year"])), EBR_LA_URL))
        title_loc = addr if addr else ("Assessment %s" % anum)
        out.append({
            "id": "la-ebr-%s" % slug(anum), "source": "baton-rouge-la",
            "title": "%s, Baton Rouge (adjudicated parcel)" % title_loc,
            "state": "LA", "county": "East Baton Rouge", "locality": "Baton Rouge", "apn": anum,
            "acres": None, "price": None, "price_kind": "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": EBR_LA_URL, "address": addr,
            "lat": lat, "lon": lon, "geometry": None, "facts": facts,
            "tags": ["adjudicated tax-sale parcel", "louisiana", "auction terms apply"],
        })
    return out


def baton_rouge_la(fetch, now, warn):
    q = urllib.parse.urlencode({
        "$where": "tax_roll_year='2023' AND sum_tol_as='0' AND geolocation IS NOT NULL AND physadd IS NOT NULL",
        "$select": "assessment_num,physadd,subd,lot,legal,tax_roll_year,council_district_no,zip_code,geolocation",
        "$order": "assessment_num", "$limit": "500",
    })
    batch = fetch.json(EBR_LA_API + "?" + q)
    if not isinstance(batch, list):
        raise StructureError("East Baton Rouge Socrata API changed")
    rows = parse_ebr_la_rows(batch, warn)
    if len(rows) < 50:
        raise StructureError("only %d Baton Rouge adjudicated parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Cherry Hill Vacant Lots (NJ)

CHERRYHILL_NJ_GIS = "https://services5.arcgis.com/UFyA9soK8NRbWhx7/arcgis/rest/services/TWP_Owned_Vacant_Lots_No_Intersect/FeatureServer/0/query"
CHERRYHILL_NJ_URL = "https://www.chnj.gov/"


def parse_cherryhill_nj_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        uid = clean(str(a.get("UNIQUEID") or a.get("X_UID") or ""))
        if not uid or uid in seen:
            continue
        seen.add(uid)
        blk = clean(str(a.get("BLOCK") or ""))
        lot = clean(str(a.get("LOT") or ""))
        street = clean(str(a.get("HADD") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("CACRES")) or rings_acres(rings)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "Cherry Hill Township Owned Vacant Lot", CHERRYHILL_NJ_URL, "cherryhill_nj"),
            fact("parcel_number", "Block %s / Lot %s" % (blk, lot) if blk else uid, CHERRYHILL_NJ_URL),
            fact("price", "Municipal land sale auction terms via Cherry Hill Township", CHERRYHILL_NJ_URL, "cherryhill_nj"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, CHERRYHILL_NJ_URL, "gis_area"))
        title_loc = street if street else ("Block %s Lot %s" % (blk, lot))
        row = {
            "id": "nj-ch-%s" % slug(uid), "source": "cherry-hill-nj",
            "title": "%s, Cherry Hill (township vacant lot)" % title_loc,
            "state": "NJ", "county": "Camden", "locality": "Cherry Hill", "apn": uid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": CHERRYHILL_NJ_URL, "address": street,
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["township vacant lot", "new jersey"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(CHERRYHILL_NJ_GIS, "UNIQUEID='%s'" % uid.replace("'", "''")), "Camden County / Cherry Hill GIS")
        out.append(row)
    return out


def cherry_hill_nj(fetch, now, warn):
    q = urllib.parse.urlencode({
        "f": "json", "where": "1=1",
        "outFields": "UNIQUEID,X_UID,BLOCK,LOT,HADD,CACRES,MUN",
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6", "resultRecordCount": "500",
    })
    data = fetch.json(CHERRYHILL_NJ_GIS + "?" + q)
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("Cherry Hill NJ ArcGIS response changed")
    rows = parse_cherryhill_nj_features(data["features"], warn)
    if len(rows) < 5:
        raise StructureError("only %d Cherry Hill NJ lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- City of Orlando Vacant Lots (FL)

ORLANDO_FL_API = "https://data.cityoforlando.net/resource/bkpt-5h2w.json"
ORLANDO_FL_URL = "https://www.orlando.gov/Home"


def parse_orlando_fl_rows(raw_rows, warn):
    out, seen = [], set()
    for r in raw_rows:
        parcel = clean(str(r.get("parcel") or r.get("property_id") or ""))
        addr = clean(str(r.get("address") or "")).title()
        if not parcel or parcel in seen:
            continue
        seen.add(parcel)
        acres = number(r.get("lot_size_acres")) or (round(number(r.get("lot_size_sqft")) / 43560.0, 4) if number(r.get("lot_size_sqft")) else None)
        geo = r.get("geocoded_column") if isinstance(r.get("geocoded_column"), dict) else {}
        coords = geo.get("coordinates") if isinstance(geo.get("coordinates"), list) else []
        lat = lon = None
        if len(coords) == 2:
            try:
                lo, la = float(coords[0]), float(coords[1])
                if 28.2 <= la <= 28.8 and -81.7 <= lo <= -81.1:
                    lat, lon = round(la, 6), round(lo, 6)
            except (TypeError, ValueError):
                pass
        zoning = clean(str(r.get("zoning") or ""))
        dims = clean(str(r.get("lot_dimensions_feet") or ""))
        conforming = r.get("conforming_lot_58_1152")
        facts = [
            fact("availability", "City of Orlando Vacant Lots Inventory", ORLANDO_FL_URL, "orlando_fl"),
            fact("parcel_number", parcel, ORLANDO_FL_URL),
            fact("price", "Surplus application / disposition terms via City of Orlando", ORLANDO_FL_URL, "orlando_fl"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, ORLANDO_FL_URL))
        if dims:
            facts.append(fact("lot_area", "%s ft" % dims, ORLANDO_FL_URL))
        if zoning:
            facts.append(fact("zoning", zoning, ORLANDO_FL_URL))
        if conforming is not None:
            facts.append(fact("buildable_lot", "Yes (conforming)" if conforming else "Non-conforming", ORLANDO_FL_URL))
        out.append({
            "id": "fl-orl-%s" % slug(parcel), "source": "orlando-vacant-fl",
            "title": "%s, Orlando (city-owned vacant lot)" % (addr or ("Parcel " + parcel)),
            "state": "FL", "county": "Orange", "locality": "Orlando", "apn": parcel,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": ORLANDO_FL_URL, "address": addr,
            "lat": lat, "lon": lon, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "florida"] + (["zoned %s" % zoning] if zoning else []),
        })
    return out


def orlando_vacant_fl(fetch, now, warn):
    batch = fetch.json(ORLANDO_FL_API + "?$limit=500")
    if not isinstance(batch, list):
        raise StructureError("Orlando FL Socrata API changed")
    rows = parse_orlando_fl_rows(batch, warn)
    if len(rows) < 10:
        raise StructureError("only %d Orlando FL vacant lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Phase 5: 15 Official Agencies Across 13 New States (AL, CT, DE, IA, IN, KS, MA, MN, NE, RI, TN, VA, WV)

def _arcgis_query(fetch, gis_url, where, out_fields, count=500, extra=None):
    params = {
        "f": "json", "where": where, "outFields": out_fields,
        "outSR": "4326", "returnGeometry": "true", "geometryPrecision": "6",
        "resultRecordCount": str(count),
    }
    if extra:
        params.update(extra)
    data = fetch.json(gis_url + "?" + urllib.parse.urlencode(params))
    if not isinstance(data, dict) or "features" not in data:
        raise StructureError("ArcGIS response changed for %s" % gis_url)
    return data["features"]


# --- Delaware County / Muncie Tax Sale (IN) ---
DELAWARE_IN_GIS = "https://services6.arcgis.com/eVA2BCtRxhBWjuqd/arcgis/rest/services/Muncie_IN_Tax_Sale_Fall_2026/FeatureServer/15/query"
DELAWARE_IN_URL = "https://delawarecounty.in.gov/"


def parse_delaware_in_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("State_PIN") or a.get("Local_PIN") or a.get("Sale_ID") or ""))
        if not pin or pin in seen:
            continue
        impr = number(a.get("AV___Total_Improvements"))
        if impr and impr > 0:
            continue
        seen.add(pin)
        addr = clean(str(a.get("Property_Street") or "")).title()
        city = clean(str(a.get("Property_City") or "Muncie")).title() or "Muncie"
        bid = number(a.get("Minimum_Bid"))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings) if rings else None
        facts = [
            fact("availability", "Delaware County Fall 2026 Tax Sale (vacant land)", DELAWARE_IN_URL, "delaware_in"),
            fact("parcel_number", pin, DELAWARE_IN_URL),
        ]
        if bid:
            facts.append(fact("price", "Minimum bid $%s" % "{:,.2f}".format(bid), DELAWARE_IN_URL, "delaware_in"))
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, DELAWARE_IN_URL, "gis_area"))
        if clean(str(a.get("Legal") or "")):
            facts.append(fact("legal_description", clean(str(a["Legal"])), DELAWARE_IN_URL))
        if clean(str(a.get("Property_1") or "")):
            facts.append(fact("property_class", clean(str(a["Property_1"])), DELAWARE_IN_URL))
        title_loc = "%s (%s)" % (addr, pin) if addr else ("Parcel " + pin)
        row = {
            "id": "in-del-%s" % slug(pin), "source": "delaware-in",
            "title": "%s, %s (Indiana tax-sale land)" % (title_loc, city),
            "state": "IN", "county": "Delaware", "locality": city, "apn": pin,
            "acres": acres, "price": round(bid, 2) if bid else None,
            "price_kind": "min_bid" if bid else "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": DELAWARE_IN_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax sale auction", "vacant land", "indiana"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(DELAWARE_IN_GIS, "State_PIN='%s'" % pin.replace("'", "''")), "Delaware County IN GIS")
        out.append(row)
    return out


def delaware_in(fetch, now, warn):
    feats = _arcgis_query(fetch, DELAWARE_IN_GIS, "AV___Total_Improvements=0 OR AV___Total_Improvements IS NULL",
                          "Sale_ID,State_PIN,Local_PIN,Property_Street,Property_City,Legal,Property_1,Minimum_Bid,AV___Total_Improvements", 400)
    rows = parse_delaware_in_features(feats, warn)
    if len(rows) < 20:
        raise StructureError("only %d Delaware County IN parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Mille Lacs County Tax-Forfeited Land (MN) ---
MILLELACS_MN_GIS = "https://services6.arcgis.com/msGTRvdwc9dcDoMX/arcgis/rest/services/Tax_Forfeit_Web_Map_WFL1/FeatureServer/3/query"
MILLELACS_MN_URL = "https://www.millelacs.mn.gov/"


def parse_millelacs_mn_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("PID") or ""))
        if not pid or pid in seen:
            continue
        if clean(str(a.get("SALEABLE") or "")).lower() != "yes":
            continue
        if clean(str(a.get("STRUCTURES") or "")).lower() == "yes":
            continue
        seen.add(pid)
        sub = clean(str(a.get("POLITICAL_SUBDIVISION") or "Mille Lacs County"))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACRES")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        price = number(a.get("PRICE"))
        zoning = clean(str(a.get("ZONING_DISTRICT") or ""))
        water = clean(str(a.get("WATERFRONT") or ""))
        facts = [
            fact("availability", "Tax-Forfeited Saleable Vacant Land", MILLELACS_MN_URL, "millelacs_mn"),
            fact("parcel_number", pid, MILLELACS_MN_URL),
            fact("price", ("Minimum bid $%s" % "{:,.2f}".format(price)) if price else "Confirm current minimum bid / auction schedule with Mille Lacs County", MILLELACS_MN_URL, "millelacs_mn"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, MILLELACS_MN_URL))
        if zoning:
            facts.append(fact("zoning", zoning, MILLELACS_MN_URL))
        if water.lower() == "yes":
            facts.append(fact("waterfront", "Yes (shoreland/waterfront parcel)", MILLELACS_MN_URL))
        row = {
            "id": "mn-ml-%s" % slug(pid), "source": "mille-lacs-mn",
            "title": "%s parcel %s (Mille Lacs tax-forfeited land)" % (sub, pid),
            "state": "MN", "county": "Mille Lacs", "locality": sub, "apn": pid,
            "acres": acres, "price": round(price, 2) if price else None,
            "price_kind": "min_bid" if price else "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": MILLELACS_MN_URL,
            "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax-forfeited land", "minnesota"] + (["waterfront"] if water.lower() == "yes" else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(MILLELACS_MN_GIS, "PID='%s'" % pid.replace("'", "''")), "Mille Lacs County MN GIS")
        out.append(row)
    return out


def mille_lacs_mn(fetch, now, warn):
    feats = _arcgis_query(fetch, MILLELACS_MN_GIS, "SALEABLE='Yes'",
                          "PID,SALEABLE,POLITICAL_SUBDIVISION,PRICE,ACRES,SALE_TYPE,STRUCTURES,ZONING_DISTRICT,WATERFRONT", 200)
    rows = parse_millelacs_mn_features(feats, warn)
    if len(rows) < 2:
        raise StructureError("only %d Mille Lacs MN parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Otter Tail County Tax-Forfeited Land (MN) ---
OTTERTAIL_MN_GIS = "https://services3.arcgis.com/Pg1yLLk3jMuhxBKI/arcgis/rest/services/TaxForfeitParcelBoundaries/FeatureServer/0/query"
OTTERTAIL_MN_URL = "https://ottertailcounty.gov/"


def parse_ottertail_mn_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("PIN") or ""))
        if not pin or pin.upper() == "ROW" or pin in seen:
            continue
        seen.add(pin)
        addr = clean(str(a.get("PHYSADDR") or "")).title()
        city = clean(str(a.get("PHYSCITY") or "Otter Tail County")).title() or "Otter Tail County"
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACRES")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "Otter Tail County Tax-Forfeited Parcel", OTTERTAIL_MN_URL, "ottertail_mn"),
            fact("parcel_number", pin, OTTERTAIL_MN_URL),
            fact("price", "Confirm auction / over-the-counter pricing with Otter Tail County", OTTERTAIL_MN_URL, "ottertail_mn"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, OTTERTAIL_MN_URL))
        if clean(str(a.get("LEGAL") or "")):
            facts.append(fact("legal_description", clean(str(a["LEGAL"]))[:180], OTTERTAIL_MN_URL))
        title_loc = "%s (%s)" % (addr, pin) if addr else ("Parcel " + pin)
        row = {
            "id": "mn-ot-%s" % slug(pin), "source": "otter-tail-mn",
            "title": "%s, %s (Otter Tail tax-forfeited land)" % (title_loc, city),
            "state": "MN", "county": "Otter Tail", "locality": city, "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": OTTERTAIL_MN_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax-forfeited land", "minnesota"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(OTTERTAIL_MN_GIS, "PIN='%s'" % pin.replace("'", "''")), "Otter Tail County MN GIS")
        out.append(row)
    return out


def otter_tail_mn(fetch, now, warn):
    feats = _arcgis_query(fetch, OTTERTAIL_MN_GIS, "1=1", "PIN,ACRES,LEGAL,PHYSADDR,PHYSCITY", 200)
    rows = parse_ottertail_mn_features(feats, warn)
    if len(rows) < 3:
        raise StructureError("only %d Otter Tail MN parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Richmond Surplus Vacant Properties (VA) ---
RICHMOND_VA_GIS = "https://services1.arcgis.com/k3vhq11XkBNeeOfM/arcgis/rest/services/City_Surplus_Properties___2025/FeatureServer/0/query"
RICHMOND_VA_URL = "https://www.rva.gov/"


def parse_richmond_va_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("PIN") or a.get("ParcelID") or ""))
        if not pin or pin in seen:
            continue
        if number(a.get("DwellingValue")):
            continue
        seen.add(pin)
        rings = (f.get("geometry") or {}).get("rings") or []
        sqft = number(a.get("LandSqFt"))
        acres = round(sqft / 43560.0, 4) if sqft else (rings_acres(rings) if rings else None)
        luse = clean(str(a.get("LandUse") or a.get("PropertyClass") or ""))
        nhood = clean(str(a.get("ProvalAsmtNhood") or ""))
        facts = [
            fact("availability", "City of Richmond Surplus Vacant Property", RICHMOND_VA_URL, "richmond_va"),
            fact("parcel_number", pin, RICHMOND_VA_URL),
            fact("price", "Surplus disposition / RFP terms via City of Richmond", RICHMOND_VA_URL, "richmond_va"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, RICHMOND_VA_URL))
        if luse:
            facts.append(fact("property_class", luse, RICHMOND_VA_URL))
        if nhood:
            facts.append(fact("neighborhood", nhood, RICHMOND_VA_URL))
        row = {
            "id": "va-rva-%s" % slug(pin), "source": "richmond-va",
            "title": "Richmond surplus parcel %s (city-owned vacant land)" % pin,
            "state": "VA", "county": "Richmond City", "locality": "Richmond", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": RICHMOND_VA_URL,
            "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city surplus land", "virginia"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(RICHMOND_VA_GIS, "PIN='%s'" % pin.replace("'", "''")), "City of Richmond VA GIS")
        out.append(row)
    return out


def richmond_va(fetch, now, warn):
    feats = _arcgis_query(fetch, RICHMOND_VA_GIS, "DwellingValue=0 OR DwellingValue IS NULL",
                          "ParcelID,PIN,DwellingValue,LandSqFt,PropertyClass,LandUse,ProvalAsmtNhood", 250)
    rows = parse_richmond_va_features(feats, warn)
    if len(rows) < 10:
        raise StructureError("only %d Richmond VA surplus parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Montgomery Surplus Property (AL) ---
MONTGOMERY_AL_GIS = "https://services7.arcgis.com/xNUwUjOJqYE54USz/arcgis/rest/services/Surplus_City_Property_point/FeatureServer/0/query"
MONTGOMERY_AL_URL = "https://www.montgomeryal.gov/"


def parse_montgomery_al_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if clean(str(a.get("DISPLAY") or "")).upper() != "YES":
            continue
        pid = clean(str(a.get("PARCEL_NUM") or a.get("TAX_MAP") or a.get("FID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        g = f.get("geometry") or {}
        lat = lon = None
        if isinstance(g.get("x"), (int, float)) and isinstance(g.get("y"), (int, float)):
            if 32.0 <= g["y"] <= 32.7 and -86.7 <= g["x"] <= -85.9:
                lat, lon = round(float(g["y"]), 6), round(float(g["x"]), 6)
        snum = clean(str(a.get("STREET_NUM") or ""))
        snam = clean(str(a.get("STREET_NAM") or "")).title()
        addr = ("%s %s" % (snum, snam)).strip() if snam else ""
        loc = clean(str(a.get("LOCATION") or ""))
        acres = number(a.get("CALC_ACRE")) or (round(number(a.get("SQ_FT")) / 43560.0, 4) if number(a.get("SQ_FT")) else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Montgomery General Surplus Property", MONTGOMERY_AL_URL, "montgomery_al"),
            fact("parcel_number", pid, MONTGOMERY_AL_URL),
            fact("price", "Surplus bid / offer review via City of Montgomery", MONTGOMERY_AL_URL, "montgomery_al"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, MONTGOMERY_AL_URL))
        if loc:
            facts.append(fact("location_note", loc, MONTGOMERY_AL_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        out.append({
            "id": "al-mgm-%s" % slug(pid), "source": "montgomery-al",
            "title": "%s, Montgomery (surplus city land)" % title_loc,
            "state": "AL", "county": "Montgomery", "locality": "Montgomery", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": MONTGOMERY_AL_URL,
            "address": addr, "lat": lat, "lon": lon, "geometry": None, "facts": facts,
            "tags": ["city surplus land", "alabama"],
        })
    return out


def montgomery_al(fetch, now, warn):
    feats = _arcgis_query(fetch, MONTGOMERY_AL_GIS, "DISPLAY='YES'",
                          "FID,CALC_ACRE,TAX_MAP,PARCEL_NUM,STREET_NUM,STREET_NAM,LOCATION,STRATEGY,DISPLAY,SQ_FT", 250)
    rows = parse_montgomery_al_features(feats, warn)
    if len(rows) < 10:
        raise StructureError("only %d Montgomery AL surplus parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Waterloo Properties For Sale (IA) ---
WATERLOO_IA_GIS = "https://services1.arcgis.com/QOAXA4I2iTKKdBuy/arcgis/rest/services/Industrial_Park_Properties_For_Sale_view/FeatureServer/34/query"
WATERLOO_IA_URL = "https://www.cityofwaterlooiowa.com/"


def parse_waterloo_ia_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        oid = clean(str(a.get("OBJECTID") or ""))
        pid = clean(str(a.get("ParcelNumber") or "")) or ("WAT-" + oid)
        key = pid if pid not in seen else ("%s-%s" % (pid, oid))
        if not key or key in seen:
            continue
        seen.add(key)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Area")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        zoning = clean(str(a.get("Zoning") or ""))
        tif = clean(str(a.get("TIFDistrict") or ""))
        use = clean(str(a.get("PossibleUse") or ""))
        facts = [
            fact("availability", "City of Waterloo Property For Sale", WATERLOO_IA_URL, "waterloo_ia"),
            fact("parcel_number", key, WATERLOO_IA_URL),
            fact("price", "Contact City of Waterloo Community Planning & Development for sale terms", WATERLOO_IA_URL, "waterloo_ia"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, WATERLOO_IA_URL))
        if zoning:
            facts.append(fact("zoning", zoning, WATERLOO_IA_URL))
        if tif:
            facts.append(fact("sale_program", "TIF District: %s" % tif, WATERLOO_IA_URL))
        if use:
            facts.append(fact("possible_use", use, WATERLOO_IA_URL))
        row = {
            "id": "ia-wat-%s" % slug(key), "source": "waterloo-ia",
            "title": "%s site %s, Waterloo (city land for sale)" % (tif or "Development", key),
            "state": "IA", "county": "Black Hawk", "locality": "Waterloo", "apn": key,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": WATERLOO_IA_URL,
            "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city land for sale", "iowa"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings and oid:
            apply_geometry(row, rings, one_parcel_url(WATERLOO_IA_GIS, "OBJECTID=%s" % oid), "City of Waterloo IA GIS")
        out.append(row)
    return out


def waterloo_ia(fetch, now, warn):
    feats = _arcgis_query(fetch, WATERLOO_IA_GIS, "1=1",
                          "OBJECTID,Dimensions,Zoning,TIFDistrict,Area,ParcelNumber,PossibleUse", 250)
    rows = parse_waterloo_ia_features(feats, warn)
    if len(rows) < 10:
        raise StructureError("only %d Waterloo IA parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Wyandotte County / Kansas City KS Land Bank (KS) ---
WYANDOTTE_KS_GIS = "https://services1.arcgis.com/Qo2HHQp8vgPs2wg3/arcgis/rest/services/Land_Bank2/FeatureServer/0/query"
WYANDOTTE_KS_URL = "https://www.wycokck.org/"


def parse_wyandotte_ks_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if clean(str(a.get("VACANT") or "")).upper() != "Y":
            continue
        pid = clean(str(a.get("PARCEL") or a.get("STATE_ID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        parts = [clean(str(a.get(k) or "")) for k in ("NUMB", "DIR", "ST_NAME", "SUFX")]
        addr = " ".join(p for p in parts if p).title()
        city = clean(str(a.get("CITY") or "Kansas City")).title() or "Kansas City"
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACRE")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "Wyandotte County / KCK Land Bank Vacant Parcel", WYANDOTTE_KS_URL, "wyandotte_ks"),
            fact("parcel_number", pid, WYANDOTTE_KS_URL),
            fact("price", "Application / program pricing via Wyandotte County Land Bank", WYANDOTTE_KS_URL, "wyandotte_ks"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, WYANDOTTE_KS_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "ks-wyc-%s" % slug(pid), "source": "wyandotte-ks",
            "title": "%s, %s (Wyandotte land bank lot)" % (title_loc, city),
            "state": "KS", "county": "Wyandotte", "locality": city, "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": WYANDOTTE_KS_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "kansas"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(WYANDOTTE_KS_GIS, "PARCEL='%s'" % pid.replace("'", "''")), "Wyandotte County KS GIS")
        out.append(row)
    return out


def wyandotte_ks(fetch, now, warn):
    feats = _arcgis_query(fetch, WYANDOTTE_KS_GIS, "VACANT='Y'",
                          "PARCEL,ACRE,NUMB,DIR,ST_NAME,SUFX,CITY,VACANT", 350, {"orderByFields": "ACRE DESC"})
    rows = parse_wyandotte_ks_features(feats, warn)
    if len(rows) < 50:
        raise StructureError("only %d Wyandotte KS land bank lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Shawnee County / Topeka Parcels For Sale (KS) ---
SHAWNEE_KS_GIS = "https://services1.arcgis.com/EvtgI3PZ9PyCGJZS/arcgis/rest/services/Parcel4SaleMap/FeatureServer/0/query"
SHAWNEE_KS_URL = "https://www.snco.gov/"


def parse_shawnee_ks_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("BLDGVAL")):
            continue
        pin = clean(str(a.get("PIN") or a.get("OBJECTID") or ""))
        if not pin or pin in seen:
            continue
        seen.add(pin)
        addr = clean(str(a.get("PADDRESS") or "")).title()
        price = number(a.get("SALE_PRICE")) or number(a.get("PRICE"))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACRES")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        comments = clean(str(a.get("COMMENTS") or ""))
        facts = [
            fact("availability", "Shawnee County Vacant Parcel For Sale", SHAWNEE_KS_URL, "shawnee_ks"),
            fact("parcel_number", pin, SHAWNEE_KS_URL),
        ]
        if price:
            facts.append(fact("price", "Listed sale price $%s" % "{:,.2f}".format(price), SHAWNEE_KS_URL, "shawnee_ks"))
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, SHAWNEE_KS_URL))
        if comments and comments.upper() != "NA":
            facts.append(fact("agency_notes", comments, SHAWNEE_KS_URL))
        title_loc = "%s (%s)" % (addr, pin) if addr else ("Parcel " + pin)
        row = {
            "id": "ks-snco-%s" % slug(pin), "source": "shawnee-ks",
            "title": "%s, Topeka (Shawnee County land for sale)" % title_loc,
            "state": "KS", "county": "Shawnee", "locality": "Topeka", "apn": pin,
            "acres": acres, "price": round(price, 2) if price else None,
            "price_kind": "cash" if price else "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": SHAWNEE_KS_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["fixed price", "county land for sale", "kansas"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(SHAWNEE_KS_GIS, "PIN='%s'" % pin.replace("'", "''")), "Shawnee County KS GIS")
        out.append(row)
    return out


def shawnee_ks(fetch, now, warn):
    feats = _arcgis_query(fetch, SHAWNEE_KS_GIS, "BLDGVAL=0 OR BLDGVAL IS NULL",
                          "OBJECTID,PIN,PADDRESS,ACRES,BLDGVAL,SALE_PRICE,PRICE,COMMENTS", 100)
    rows = parse_shawnee_ks_features(feats, warn)
    if len(rows) < 2:
        raise StructureError("only %d Shawnee County KS parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Wilmington Land Bank Side Lot Parcels (DE) ---
WILMINGTON_DE_GIS = "https://services.arcgis.com/hQ3wdpbjO3fPf612/arcgis/rest/services/LandBankSideLotParcels_Web_WilmDE/FeatureServer/0/query"
WILMINGTON_DE_URL = "https://www.wilmingtonde.gov/"


def parse_wilmington_de_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("L0NCC_REST_Parcel_Data_PRCLID") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("L0NCC_REST_Parcel_Data_ADDRESS") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("L0NCC_REST_Parcel_Data_LOTSZ")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "Wilmington Land Bank Side-Lot Parcel", WILMINGTON_DE_URL, "wilmington_de"),
            fact("parcel_number", pid, WILMINGTON_DE_URL),
            fact("price", "Land Bank side-lot application & program pricing via Wilmington", WILMINGTON_DE_URL, "wilmington_de"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, WILMINGTON_DE_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "de-wilm-%s" % slug(pid), "source": "wilmington-de",
            "title": "%s, Wilmington (land bank parcel)" % title_loc,
            "state": "DE", "county": "New Castle", "locality": "Wilmington", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": WILMINGTON_DE_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "delaware"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(WILMINGTON_DE_GIS, "L0NCC_REST_Parcel_Data_PRCLID='%s'" % pid.replace("'", "''")), "City of Wilmington DE GIS")
        out.append(row)
    return out


def wilmington_de(fetch, now, warn):
    feats = _arcgis_query(fetch, WILMINGTON_DE_GIS, "1=1",
                          "OBJECTID,L0NCC_REST_Parcel_Data_PRCLID,L0NCC_REST_Parcel_Data_LOTSZ,L0NCC_REST_Parcel_Data_ADDRESS", 200)
    rows = parse_wilmington_de_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Wilmington DE land bank parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Hartford City-Owned Vacant Lots (CT) ---
HARTFORD_CT_GIS = "https://utility.arcgis.com/usrsvcs/servers/8e4ef8c879594a6f8f01805e7d0b0235/rest/services/CityOwnedPropertyForAGSOL/MapServer/0/query"
HARTFORD_CT_URL = "https://www.hartfordct.gov/"


def parse_hartford_ct_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        luse = clean(str(a.get("LAND_USE") or ""))
        if "vacant" not in luse.lower():
            continue
        pid = clean(str(a.get("PARCEL_ID") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("Address") or ""))
        rings = (f.get("geometry") or {}).get("rings") or []
        sqft = number(a.get("LOT_SIZE___SQ__FT__"))
        acres = round(sqft / 43560.0, 4) if sqft else (rings_acres(rings) if rings else None)
        zoning = clean(str(a.get("ZONE") or ""))
        facts = [
            fact("availability", "City of Hartford City-Owned Vacant Lot", HARTFORD_CT_URL, "hartford_ct"),
            fact("parcel_number", pid, HARTFORD_CT_URL),
            fact("price", "Disposition application / terms via City of Hartford", HARTFORD_CT_URL, "hartford_ct"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, HARTFORD_CT_URL))
        if zoning:
            facts.append(fact("zoning", zoning, HARTFORD_CT_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "ct-hfd-%s" % slug(pid), "source": "hartford-ct",
            "title": "%s, Hartford (city-owned vacant lot)" % title_loc,
            "state": "CT", "county": "Hartford", "locality": "Hartford", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": HARTFORD_CT_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "connecticut"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(HARTFORD_CT_GIS, "PARCEL_ID='%s'" % pid.replace("'", "''")), "City of Hartford CT GIS")
        out.append(row)
    return out


def hartford_ct(fetch, now, warn):
    feats = _arcgis_query(fetch, HARTFORD_CT_GIS, "1=1",
                          "OBJECTID,PARCEL_ID,Address,LAND_USE,ZONE,LOT_SIZE___SQ__FT__", 200)
    rows = parse_hartford_ct_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Hartford CT vacant lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Omaha City-Owned Vacant Land (NE) ---
OMAHA_NE_GIS = "https://services1.arcgis.com/tIBLyYZX96jUntYm/arcgis/rest/services/Parcels_City_Owned/FeatureServer/3/query"
OMAHA_NE_URL = "https://www.cityofomaha.org/"


def parse_omaha_ne_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("NUMBLDGS")) or number(a.get("IMPROVEMEN")):
            continue
        pin = clean(str(a.get("PIN") or ""))
        addr = clean(str(a.get("PROPERTY_A") or "")).title()
        if not pin or not addr or pin in seen:
            continue
        seen.add(pin)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACRES")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Omaha City-Owned Vacant Parcel", OMAHA_NE_URL, "omaha_ne"),
            fact("parcel_number", pin, OMAHA_NE_URL),
            fact("price", "Surplus property inquiry & conveyance review via City of Omaha", OMAHA_NE_URL, "omaha_ne"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, OMAHA_NE_URL))
        if clean(str(a.get("LEGAL1") or "")):
            facts.append(fact("legal_description", clean(str(a["LEGAL1"])), OMAHA_NE_URL))
        row = {
            "id": "ne-oma-%s" % slug(pin), "source": "omaha-ne",
            "title": "%s (%s), Omaha (city-owned vacant lot)" % (addr, pin),
            "state": "NE", "county": "Douglas", "locality": "Omaha", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": OMAHA_NE_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "nebraska"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(OMAHA_NE_GIS, "PIN='%s'" % pin.replace("'", "''")), "City of Omaha / Douglas County GIS")
        out.append(row)
    return out


def omaha_ne(fetch, now, warn):
    feats = _arcgis_query(fetch, OMAHA_NE_GIS, "NUMBLDGS=0 AND IMPROVEMEN=0 AND ACRES>=0.05 AND ACRES<=20 AND PROPERTY_A IS NOT NULL",
                          "PIN,PROPERTY_A,ACRES,NUMBLDGS,IMPROVEMEN,LEGAL1", 250, {"orderByFields": "ACRES DESC"})
    rows = parse_omaha_ne_features(feats, warn)
    if len(rows) < 20:
        raise StructureError("only %d Omaha NE vacant parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Bluefield Municipal Land Bank (WV) ---
BLUEFIELD_WV_GIS = "https://services5.arcgis.com/56UKT5NHVCJyli9q/arcgis/rest/services/Municipal_Land_Bank_Map1_WFL1/FeatureServer/0/query"
BLUEFIELD_WV_URL = "https://www.bluefieldwv.gov/"


def parse_bluefield_wv_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("GISPID") or a.get("CleanParce") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("FullPhysic") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acres_C")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        zoning = clean(str(a.get("Zone") or ""))
        facts = [
            fact("availability", "Bluefield Municipal Land Bank Property", BLUEFIELD_WV_URL, "bluefield_wv"),
            fact("parcel_number", pid, BLUEFIELD_WV_URL),
            fact("price", "Land Bank purchase application via City of Bluefield", BLUEFIELD_WV_URL, "bluefield_wv"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, BLUEFIELD_WV_URL))
        if zoning:
            facts.append(fact("zoning", zoning, BLUEFIELD_WV_URL))
        if clean(str(a.get("FullLegalD") or "")):
            facts.append(fact("legal_description", clean(str(a["FullLegalD"]))[:180], BLUEFIELD_WV_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "wv-blf-%s" % slug(pid), "source": "bluefield-wv",
            "title": "%s, Bluefield (municipal land bank)" % title_loc,
            "state": "WV", "county": "Mercer", "locality": "Bluefield", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": BLUEFIELD_WV_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "west virginia"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(BLUEFIELD_WV_GIS, "GISPID='%s'" % pid.replace("'", "''")), "City of Bluefield WV GIS")
        out.append(row)
    return out


def bluefield_wv(fetch, now, warn):
    feats = _arcgis_query(fetch, BLUEFIELD_WV_GIS, "1=1",
                          "OBJECTID,GISPID,CleanParce,Acres_C,FullPhysic,FullLegalD,Zone", 150)
    rows = parse_bluefield_wv_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Bluefield WV land bank parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Memphis Surplus Vacant Properties (TN) ---
MEMPHIS_TN_GIS = "https://services2.arcgis.com/saWmpKJIUAjyyNVc/arcgis/rest/services/Soulsville_surplus_properties/FeatureServer/1/query"
MEMPHIS_TN_URL = "https://www.memphistn.gov/"


def parse_memphis_tn_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if "vacant" not in clean(str(a.get("LANDUSE") or "")).lower():
            continue
        pid = clean(str(a.get("PARID") or a.get("FID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("PAR_ADDR1") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acres")) or (round(number(a.get("SF")) / 43560.0, 4) if number(a.get("SF")) else (rings_acres(rings) if rings else None))
        if acres:
            acres = round(acres, 4)
        zoning = clean(str(a.get("CurrentZon") or ""))
        facts = [
            fact("availability", "City of Memphis Surplus Vacant Property", MEMPHIS_TN_URL, "memphis_tn"),
            fact("parcel_number", pid, MEMPHIS_TN_URL),
            fact("price", "Surplus property purchase review via City of Memphis", MEMPHIS_TN_URL, "memphis_tn"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, MEMPHIS_TN_URL))
        if zoning:
            facts.append(fact("zoning", zoning, MEMPHIS_TN_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "tn-mem-%s" % slug(pid), "source": "memphis-tn",
            "title": "%s, Memphis (city surplus vacant lot)" % title_loc,
            "state": "TN", "county": "Shelby", "locality": "Memphis", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": MEMPHIS_TN_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city surplus land", "tennessee"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(MEMPHIS_TN_GIS, "PARID='%s'" % pid.replace("'", "''")), "City of Memphis TN GIS")
        out.append(row)
    return out


def memphis_tn(fetch, now, warn):
    feats = _arcgis_query(fetch, MEMPHIS_TN_GIS, "1=1",
                          "FID,PARID,PAR_ADDR1,LANDUSE,SF,Acres,CurrentZon", 150)
    rows = parse_memphis_tn_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Memphis TN surplus vacant lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Warwick Tax-Title Vacant Land (RI) ---
WARWICK_RI_GIS = "https://services5.arcgis.com/UUWM43GOOZc20QEh/arcgis/rest/services/tax_title_warwick_coa/FeatureServer/0/query"
WARWICK_RI_URL = "https://www.warwickri.gov/"
WARWICK_VACANT = ("vac res land", "devel land", "com unb", "farm/forest mdl 00")


def parse_warwick_ri_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        luse = clean(str(a.get("MSLANDUSED") or ""))
        if luse.lower() not in WARWICK_VACANT:
            continue
        pid = clean(str(a.get("MSPARCELID") or a.get("MSGISID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("MSLOCATION") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("MSAREACAC")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Warwick Tax-Title Vacant Land", WARWICK_RI_URL, "warwick_ri"),
            fact("parcel_number", pid, WARWICK_RI_URL),
            fact("price", "Confirm tax-title auction / redemption terms with City of Warwick", WARWICK_RI_URL, "warwick_ri"),
            fact("property_class", luse, WARWICK_RI_URL),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, WARWICK_RI_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "ri-war-%s" % slug(pid), "source": "warwick-ri",
            "title": "%s, Warwick (tax-title vacant land)" % title_loc,
            "state": "RI", "county": "Kent", "locality": "Warwick", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": WARWICK_RI_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax-title land", "vacant land", "rhode island"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(WARWICK_RI_GIS, "MSPARCELID='%s'" % pid.replace("'", "''")), "City of Warwick RI GIS")
        out.append(row)
    return out


def warwick_ri(fetch, now, warn):
    feats = _arcgis_query(fetch, WARWICK_RI_GIS, "MSAREACAC>=0.05",
                          "MSGISID,MSPARCELID,MSLOCATION,MSAREACAC,MSLANDUSED", 300, {"orderByFields": "MSAREACAC DESC"})
    rows = parse_warwick_ri_features(feats, warn)
    if len(rows) < 20:
        raise StructureError("only %d Warwick RI tax-title lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Boston MOH City-Owned Land (MA) ---
BOSTON_MA_GIS = "https://services.arcgis.com/sFnw0xNflSi8J0uh/arcgis/rest/services/City_Property_Audit_2027/FeatureServer/0/query"
BOSTON_MA_URL = "https://www.boston.gov/departments/housing"


def parse_boston_ma_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if clean(str(a.get("Care_and_Custody") or "")).upper() != "MOH":
            continue
        pid = clean(str(a.get("Parcel") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("Address") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        sqft = number(a.get("Lot_Size_SF"))
        acres = round(sqft / 43560.0, 4) if sqft else (rings_acres(rings) if rings else None)
        facts = [
            fact("availability", "City of Boston Mayor's Office of Housing (MOH) Land Inventory", BOSTON_MA_URL, "boston_ma"),
            fact("parcel_number", pid, BOSTON_MA_URL),
            fact("price", "RFP / disposition guidelines via Boston Mayor's Office of Housing", BOSTON_MA_URL, "boston_ma"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, BOSTON_MA_URL))
        if sqft:
            facts.append(fact("lot_area", "%s square feet" % "{:,}".format(int(round(sqft))), BOSTON_MA_URL, "stl_area"))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "ma-bos-%s" % slug(pid), "source": "boston-ma",
            "title": "%s, Boston (MOH city-owned parcel)" % title_loc,
            "state": "MA", "county": "Suffolk", "locality": "Boston", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": BOSTON_MA_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned land", "massachusetts"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(BOSTON_MA_GIS, "Parcel='%s'" % pid.replace("'", "''")), "City of Boston MA GIS")
        out.append(row)
    return out


def boston_ma(fetch, now, warn):
    feats = _arcgis_query(fetch, BOSTON_MA_GIS, "Care_and_Custody='MOH' AND Lot_Size_SF>=1500",
                          "OBJECTID,Parcel,Address,Care_and_Custody,Lot_Size_SF", 300, {"orderByFields": "Lot_Size_SF DESC"})
    rows = parse_boston_ma_features(feats, warn)
    if len(rows) < 20:
        raise StructureError("only %d Boston MA MOH parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Phase 6: Final 14 States -> 50/50 ALL U.S. STATES (WY, OK, MS, SC, OR, HI, NV, NH, SD, ND, VT, MT, ID, ME)

# --- Albany County 2026 Tax Sale Vacant Land (WY) ---
ALBANY_WY_GIS = "https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services/2026TAXSALEPROP_1ST/FeatureServer/0/query"
ALBANY_WY_URL = "https://www.albanycountywy.gov/"


def parse_albany_wy_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("pidn") or a.get("accountno") or a.get("FID") or ""))
        if not pid or pid in seen:
            continue
        lv, tv = number(a.get("landval")), number(a.get("totalval"))
        if lv and tv and tv > lv * 1.05:
            continue
        seen.add(pid)
        addr = clean(str(a.get("st_address") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("grossacres")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        desc = clean(str(a.get("descript") or ""))
        atype = clean(str(a.get("accttype") or ""))
        facts = [
            fact("availability", "Albany County 2026 Tax Sale (unimproved land)", ALBANY_WY_URL, "albany_wy"),
            fact("parcel_number", pid, ALBANY_WY_URL),
            fact("price", "Confirm delinquent tax sale amount & redemption rules with Albany County Treasurer", ALBANY_WY_URL, "albany_wy"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, ALBANY_WY_URL))
        if atype:
            facts.append(fact("property_class", atype, ALBANY_WY_URL))
        if desc:
            facts.append(fact("legal_description", desc[:180], ALBANY_WY_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "wy-alb-%s" % slug(pid), "source": "albany-wy",
            "title": "%s, Albany County (Wyoming tax-sale land)" % title_loc,
            "state": "WY", "county": "Albany", "locality": "Laramie", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": ALBANY_WY_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax sale auction", "vacant land", "wyoming"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(ALBANY_WY_GIS, "pidn='%s'" % pid.replace("'", "''")), "Albany County WY GIS")
        out.append(row)
    return out


def albany_wy(fetch, now, warn):
    feats = _arcgis_query(fetch, ALBANY_WY_GIS, "landval=totalval AND landval>0",
                          "FID,pidn,accountno,st_address,descript,grossacres,landval,totalval,accttype", 200)
    rows = parse_albany_wy_features(feats, warn)
    if len(rows) < 3:
        raise StructureError("only %d Albany County WY parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Oklahoma DOT Statewide Surplus Property (OK) ---
ODOT_OK_GIS = "https://services6.arcgis.com/RBtoEUQ2lmN0K3GY/arcgis/rest/services/Surplus_Property_Public_Current/FeatureServer/0/query"
ODOT_OK_URL = "https://oklahoma.gov/odot.html"


def parse_odot_ok_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        oid = clean(str(a.get("OBJECTID_1") or ""))
        name = clean(str(a.get("Name") or a.get("Job_Piece_Vault") or ""))
        pnum = clean(str(a.get("Parcel") or ""))
        pid = ("%s-%s" % (name, pnum)).strip("-") or ("ODOT-" + oid)
        if not pid or pid in seen:
            pid = "%s-%s" % (pid, oid)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        county = clean(str(a.get("County") or "Oklahoma")).title() or "Oklahoma"
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acres_Remaining")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        plss_bits = [x for x in (
            ("Sec %s" % clean(str(a.get("Section")))) if a.get("Section") else "",
            ("Twp %s" % clean(str(a.get("Township")))) if a.get("Township") else "",
            ("Rng %s" % clean(str(a.get("Range")))) if a.get("Range") else "",
        ) if x]
        facts = [
            fact("availability", "Oklahoma DOT Current Surplus Property", ODOT_OK_URL, "odot_ok"),
            fact("parcel_number", pid, ODOT_OK_URL),
            fact("price", "Sealed-bid / public surplus sale terms via Oklahoma DOT", ODOT_OK_URL, "odot_ok"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, ODOT_OK_URL))
        if plss_bits:
            facts.append(fact("legal_description", " ".join(plss_bits), ODOT_OK_URL))
        row = {
            "id": "ok-odot-%s" % slug(pid), "source": "odot-ok",
            "title": "%s County ODOT surplus parcel %s (Oklahoma)" % (county, pid),
            "state": "OK", "county": county, "locality": county, "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": ODOT_OK_URL,
            "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["state surplus land", "oklahoma"],
        }
        if rings and oid:
            apply_geometry(row, rings, one_parcel_url(ODOT_OK_GIS, "OBJECTID_1=%s" % oid), "Oklahoma DOT GIS")
        out.append(row)
    return out


def odot_ok(fetch, now, warn):
    feats = _arcgis_query(fetch, ODOT_OK_GIS, "1=1",
                          "OBJECTID_1,Job_Piece_Vault,Name,Parcel,County,Acres_Remaining,Section,Township,Range", 250)
    rows = parse_odot_ok_features(feats, warn)
    if len(rows) < 10:
        raise StructureError("only %d ODOT OK surplus parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- State of Mississippi Surplus Land (MS) ---
MS_SURPLUS_GIS = "https://services6.arcgis.com/rdiy8o2SBpQHoL4Q/arcgis/rest/services/State_Of_MS_Surplus/FeatureServer/0/query"
MS_SURPLUS_URL = "https://www.sos.ms.gov/public-lands"


def parse_ms_surplus_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("tv_imp")) or number(a.get("ass_imp")):
            continue
        pid = clean(str(a.get("DPIN") or a.get("PARCEL_F") or a.get("OBJECTID_12") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        snum = clean(str(a.get("loc_num") or ""))
        snam = clean(str(a.get("loc_alpha") or "")).title()
        addr = ("%s %s" % (snum, snam)).strip() if snam else ""
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("acres_gis")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "State of Mississippi Surplus Land Inventory", MS_SURPLUS_URL, "ms_surplus"),
            fact("parcel_number", pid, MS_SURPLUS_URL),
            fact("price", "Public lands purchase application via Mississippi Secretary of State", MS_SURPLUS_URL, "ms_surplus"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, MS_SURPLUS_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "ms-sur-%s" % slug(pid), "source": "ms-surplus",
            "title": "%s, Hinds County (Mississippi state surplus land)" % title_loc,
            "state": "MS", "county": "Hinds", "locality": "Jackson", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": MS_SURPLUS_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["state surplus land", "mississippi"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(MS_SURPLUS_GIS, "DPIN='%s'" % pid.replace("'", "''")), "Mississippi State Surplus GIS")
        out.append(row)
    return out


def ms_surplus(fetch, now, warn):
    feats = _arcgis_query(fetch, MS_SURPLUS_GIS, "acres_gis>=0.05",
                          "OBJECTID_12,DPIN,PARCEL_F,acres_gis,tv_imp,ass_imp,loc_num,loc_alpha", 250, {"orderByFields": "acres_gis DESC"})
    rows = parse_ms_surplus_features(feats, warn)
    if len(rows) < 20:
        raise StructureError("only %d MS surplus parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Horry County Delinquent Tax Sale Land (SC) ---
HORRY_SC_GIS = "https://services1.arcgis.com/If0JkGr8ABreBTuS/arcgis/rest/services/DelinquentTaxParcels2025/FeatureServer/0/query"
HORRY_SC_URL = "https://www.horrycountysc.gov/"
SC_SKIP_WORDS = ("UNIT ", "CONDO", "HPR", "BLDG ", "APT ", "SUITE ", "VILLA ", "TIMESHAR", "INTERVAL", "WEEK ")


def parse_horry_sc_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        desc = clean(str(a.get("Description") or ""))
        u_desc = desc.upper()
        if any(w in u_desc for w in SC_SKIP_WORDS):
            continue
        pin = clean(str(a.get("PIN_1") or a.get("Item_Number") or a.get("OBJECTID") or ""))
        if not pin or pin in seen:
            continue
        seen.add(pin)
        bid = number(a.get("FLC_Bid_Amount"))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings) if rings else None
        facts = [
            fact("availability", "Horry County Delinquent Tax Sale Parcel", HORRY_SC_URL, "horry_sc"),
            fact("parcel_number", pin, HORRY_SC_URL),
        ]
        if bid:
            facts.append(fact("price", "Opening / FLC bid $%s" % "{:,.2f}".format(bid), HORRY_SC_URL, "horry_sc"))
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, HORRY_SC_URL, "gis_area"))
        if desc:
            facts.append(fact("legal_description", desc[:180], HORRY_SC_URL))
        row = {
            "id": "sc-hor-%s" % slug(pin), "source": "horry-sc",
            "title": "Horry County parcel %s (South Carolina tax-sale land)" % pin,
            "state": "SC", "county": "Horry", "locality": "Conway", "apn": pin,
            "acres": acres, "price": round(bid, 2) if bid else None,
            "price_kind": "min_bid" if bid else "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": HORRY_SC_URL,
            "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax sale auction", "south carolina"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(HORRY_SC_GIS, "PIN_1='%s'" % pin.replace("'", "''")), "Horry County SC GIS")
        out.append(row)
    return out


def horry_sc(fetch, now, warn):
    feats = _arcgis_query(fetch, HORRY_SC_GIS, "1=1",
                          "OBJECTID,Item_Number,PIN_1,Description,FLC_Bid_Amount", 400)
    rows = parse_horry_sc_features(feats, warn)[:220]
    if len(rows) < 20:
        raise StructureError("only %d Horry County SC tax-sale parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Portland Vacant City-Owned Land (OR) ---
PORTLAND_OR_GIS = "https://www.portlandmaps.com/od/rest/services/COP_OpenData_Property/MapServer/91/query"
PORTLAND_OR_URL = "https://www.portland.gov/"


def parse_portland_or_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("BLDGSQFT")):
            continue
        pid = clean(str(a.get("STATE_ID") or a.get("RNO") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        raw_addr = clean(str(a.get("SITEADDR") or ""))
        addr = "" if ("no situs" in raw_addr.lower() or not raw_addr) else raw_addr.title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("A_T_ACRES")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        desc = clean(str(a.get("PRPCD_DESC") or ""))
        facts = [
            fact("availability", "City of Portland Vacant City-Owned Parcel", PORTLAND_OR_URL, "portland_or"),
            fact("parcel_number", pid, PORTLAND_OR_URL),
            fact("price", "Surplus property inquiry & disposition review via City of Portland", PORTLAND_OR_URL, "portland_or"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, PORTLAND_OR_URL))
        if desc:
            facts.append(fact("property_class", desc, PORTLAND_OR_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "or-pdx-%s" % slug(pid), "source": "portland-or",
            "title": "%s, Portland (city-owned vacant land)" % title_loc,
            "state": "OR", "county": "Multnomah", "locality": "Portland", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": PORTLAND_OR_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "oregon"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(PORTLAND_OR_GIS, "STATE_ID='%s'" % pid.replace("'", "''")), "PortlandMaps Open Data GIS")
        out.append(row)
    return out


def portland_or(fetch, now, warn):
    feats = _arcgis_query(fetch, PORTLAND_OR_GIS, "OWNER1 LIKE 'CITY OF PORTLAND%' AND (BLDGSQFT=0 OR BLDGSQFT IS NULL) AND LANDUSE='VAC'",
                          "OBJECTID,STATE_ID,RNO,SITEADDR,PRPCD_DESC,BLDGSQFT,A_T_ACRES", 200)
    rows = parse_portland_or_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Portland OR vacant parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Maui Vacant Government-Owned Parcels (HI) ---
MAUI_HI_GIS = "https://services3.arcgis.com/fsrDo0QMPlK9CkZD/arcgis/rest/services/Vacant_Government_Owned_Parcels_in_West_Maui/FeatureServer/0/query"
MAUI_HI_URL = "https://www.mauicounty.gov/"


def parse_maui_hi_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("BldgValue")):
            continue
        tmk = clean(str(a.get("TMK_txt") or a.get("TMK") or a.get("OBJECTID") or ""))
        if not tmk or tmk in seen:
            continue
        seen.add(tmk)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("TaxAcres")) or number(a.get("GISAcres")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        juris = clean(str(a.get("Jurisdiction") or "Maui County"))
        facts = [
            fact("availability", "Vacant Government-Owned Parcel (West Maui)", MAUI_HI_URL, "maui_hi"),
            fact("parcel_number", "TMK " + tmk, MAUI_HI_URL),
            fact("price", "Confirm public disposition / auction eligibility with Maui County or Hawaii DLNR", MAUI_HI_URL, "maui_hi"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, MAUI_HI_URL))
        if juris:
            facts.append(fact("jurisdiction", juris, MAUI_HI_URL))
        row = {
            "id": "hi-maui-%s" % slug(tmk), "source": "maui-hi",
            "title": "West Maui TMK %s (vacant public land)" % tmk,
            "state": "HI", "county": "Maui", "locality": "Lahaina", "apn": tmk,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": MAUI_HI_URL,
            "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["public vacant land", "hawaii"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(MAUI_HI_GIS, "TMK_txt='%s'" % tmk.replace("'", "''")), "Maui County HI GIS")
        out.append(row)
    return out


def maui_hi(fetch, now, warn):
    feats = _arcgis_query(fetch, MAUI_HI_GIS, "BldgValue=0 OR BldgValue IS NULL",
                          "OBJECTID,TMK,TMK_txt,BldgValue,TaxAcres,GISAcres,Jurisdiction", 150)
    rows = parse_maui_hi_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Maui HI vacant parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Las Vegas Vacant Real Estate Assets (NV) ---
LASVEGAS_NV_GIS = "https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/CLV_Real_Estate_Assets_Open_Data/FeatureServer/0/query"
LASVEGAS_NV_URL = "https://www.lasvegasnevada.gov/"


def parse_lasvegas_nv_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if "vacant" not in clean(str(a.get("IMPROVEMENTNAME") or "")).lower():
            continue
        pid = clean(str(a.get("PARCEL") or a.get("ObjectId") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        loc = clean(str(a.get("LOCATION") or "")).title()
        g = f.get("geometry") or {}
        lat = lon = None
        la = a.get("LAT") if a.get("LAT") is not None else g.get("y")
        lo = a.get("LONG") if a.get("LONG") is not None else g.get("x")
        try:
            if la is not None and lo is not None:
                fla, flo = float(la), float(lo)
                if 35.8 <= fla <= 36.6 and -115.6 <= flo <= -114.7:
                    lat, lon = round(fla, 6), round(flo, 6)
        except (TypeError, ValueError):
            pass
        raw_ac = number(a.get("ACRES_1"))
        acres = round(raw_ac, 4) if (raw_ac and 0.01 <= raw_ac <= 500) else None
        facts = [
            fact("availability", "City of Las Vegas Vacant Real Estate Asset", LASVEGAS_NV_URL, "lasvegas_nv"),
            fact("parcel_number", pid, LASVEGAS_NV_URL),
            fact("price", "Surplus auction / RFP terms via City of Las Vegas Real Estate", LASVEGAS_NV_URL, "lasvegas_nv"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, LASVEGAS_NV_URL))
        title_loc = "%s (%s)" % (loc, pid) if loc else ("Parcel " + pid)
        out.append({
            "id": "nv-lv-%s" % slug(pid), "source": "lasvegas-nv",
            "title": "%s, Las Vegas (city-owned vacant land)" % title_loc,
            "state": "NV", "county": "Clark", "locality": "Las Vegas", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": LASVEGAS_NV_URL,
            "address": loc, "lat": lat, "lon": lon, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "nevada"],
        })
    return out


def lasvegas_nv(fetch, now, warn):
    feats = _arcgis_query(fetch, LASVEGAS_NV_GIS, "IMPROVEMENTNAME LIKE '%VACANT%'",
                          "ObjectId,PARCEL,LOCATION,IMPROVEMENTNAME,ACRES_1,LAT,LONG", 150)
    rows = parse_lasvegas_nv_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Las Vegas NV vacant parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Town of Peterborough Tax-Deeded Lands (NH) ---
PETERBOROUGH_NH_GIS = "https://services1.arcgis.com/TBWWZRJoZeMDaqgb/arcgis/rest/services/Town_Owned_Lands/FeatureServer/0/query"
PETERBOROUGH_NH_URL = "https://www.peterboroughnh.gov/"


def parse_peterborough_nh_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if clean(str(a.get("CLASSIFY") or "")).lower() != "tax":
            continue
        pid = clean(str(a.get("PIN") or a.get("PENTAMATIO") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        loc = clean(str(a.get("LOCATION") or ""))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACREAGE")) or number(a.get("Acres")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        zoning = clean(str(a.get("ZONING") or ""))
        facts = [
            fact("availability", "Town of Peterborough Tax-Deeded Land", PETERBOROUGH_NH_URL, "peterborough_nh"),
            fact("parcel_number", pid, PETERBOROUGH_NH_URL),
            fact("price", "Confirm municipal tax-deed sale schedule with Town of Peterborough", PETERBOROUGH_NH_URL, "peterborough_nh"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, PETERBOROUGH_NH_URL))
        if zoning:
            facts.append(fact("zoning", zoning, PETERBOROUGH_NH_URL))
        title_loc = "%s (%s)" % (loc, pid) if loc else ("Parcel " + pid)
        row = {
            "id": "nh-pbo-%s" % slug(pid), "source": "peterborough-nh",
            "title": "%s, Peterborough (tax-deeded land)" % title_loc,
            "state": "NH", "county": "Hillsborough", "locality": "Peterborough", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": PETERBOROUGH_NH_URL,
            "address": loc, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax-deeded land", "new hampshire"] + (["zoned %s" % zoning] if zoning else []),
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(PETERBOROUGH_NH_GIS, "PIN='%s'" % pid.replace("'", "''")), "Town of Peterborough NH GIS")
        out.append(row)
    return out


def peterborough_nh(fetch, now, warn):
    feats = _arcgis_query(fetch, PETERBOROUGH_NH_GIS, "CLASSIFY='Tax'",
                          "OBJECTID,PIN,PENTAMATIO,LOCATION,ACREAGE,Acres,CLASSIFY,ZONING", 100)
    rows = parse_peterborough_nh_features(feats, warn)
    if len(rows) < 3:
        raise StructureError("only %d Peterborough NH tax-deeded parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Yankton Vacant Municipal Lots (SD) ---
YANKTON_SD_GIS = "https://services3.arcgis.com/aVepqWph7Jkj1aWl/arcgis/rest/services/VacantLots/FeatureServer/0/query"
YANKTON_SD_URL = "https://www.cityofyankton.org/"


def parse_yankton_sd_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        loc = clean(str(a.get("Location") or ""))
        leg = clean(str(a.get("LEGALS") or ""))
        combo = (loc + " " + leg).upper()
        if any(w in combo for w in ("PARK", "CEMETERY", "AIRPORT", "SCHOOL", "WATER TOWER", "LIFT STATION", "FIRE", "LANDFILL")):
            continue
        pid = clean(str(a.get("PARCEL_ID") or a.get("OBJECTID_1") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acres_1")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Yankton Vacant Municipal Lot", YANKTON_SD_URL, "yankton_sd"),
            fact("parcel_number", pid, YANKTON_SD_URL),
            fact("price", "Confirm municipal surplus availability & bid terms with City of Yankton", YANKTON_SD_URL, "yankton_sd"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, YANKTON_SD_URL))
        if leg:
            facts.append(fact("legal_description", leg[:180], YANKTON_SD_URL))
        title_loc = "%s (%s)" % (loc.title(), pid) if loc else ("Parcel " + pid)
        row = {
            "id": "sd-ynk-%s" % slug(pid), "source": "yankton-sd",
            "title": "%s, Yankton (city-owned vacant lot)" % title_loc,
            "state": "SD", "county": "Yankton", "locality": "Yankton", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": YANKTON_SD_URL,
            "address": loc.title(), "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "south dakota"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(YANKTON_SD_GIS, "PARCEL_ID='%s'" % pid.replace("'", "''")), "City of Yankton SD GIS")
        out.append(row)
    return out


def yankton_sd(fetch, now, warn):
    feats = _arcgis_query(fetch, YANKTON_SD_GIS, "Name LIKE '%CITY OF YANKTON%'",
                          "OBJECTID_1,PARCEL_ID,Location,Acres_1,LEGALS", 250)
    rows = parse_yankton_sd_features(feats, warn)[:140]
    if len(rows) < 10:
        raise StructureError("only %d Yankton SD vacant lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Burleigh County / Bismarck Vacant Public Land (ND) ---
BURLEIGH_ND_GIS = "https://services2.arcgis.com/8r0lsT7QHelkANsD/arcgis/rest/services/Tax_Parcels_Burleigh_County_ND/FeatureServer/0/query"
BURLEIGH_ND_URL = "https://www.burleigh.gov/"


def parse_burleigh_nd_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("Commercial_Building_Market")) or number(a.get("Residential_Building_Market")):
            continue
        leg = clean(str(a.get("Legal") or ""))
        if any(w in leg.upper() for w in ("PARK", "CEMETERY", "R/W", "RIGHT OF WAY", "ROAD", "STREET", "ALLEY", "DRAIN", "POND", "STORM")):
            continue
        pid = clean(str(a.get("PID") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acres")) or (rings_acres(rings) if rings else None)
        if not acres or acres < 0.05 or acres > 160:
            continue
        acres = round(acres, 4)
        seen.add(pid)
        addr = clean(str(a.get("Property_Address") or "")).title()
        facts = [
            fact("availability", "Burleigh County / Bismarck Unimproved Public Parcel", BURLEIGH_ND_URL, "burleigh_nd"),
            fact("parcel_number", pid, BURLEIGH_ND_URL),
            fact("price", "Confirm county tax-deed / municipal surplus sale terms on burleigh.gov", BURLEIGH_ND_URL, "burleigh_nd"),
            fact("acreage", "%g acres" % acres, BURLEIGH_ND_URL),
        ]
        if leg:
            facts.append(fact("legal_description", leg[:180], BURLEIGH_ND_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "nd-bur-%s" % slug(pid), "source": "burleigh-nd",
            "title": "%s, Burleigh County (North Dakota public land)" % title_loc,
            "state": "ND", "county": "Burleigh", "locality": "Bismarck", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": BURLEIGH_ND_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["public vacant land", "north dakota"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(BURLEIGH_ND_GIS, "PID='%s'" % pid.replace("'", "''")), "Burleigh County ND GIS")
        out.append(row)
    return out


def burleigh_nd(fetch, now, warn):
    w = "(Owner='BURLEIGH COUNTY' OR Owner='CITY OF BISMARCK') AND (Commercial_Building_Market=0 OR Commercial_Building_Market IS NULL) AND (Residential_Building_Market=0 OR Residential_Building_Market IS NULL)"
    feats = _arcgis_query(fetch, BURLEIGH_ND_GIS, w,
                          "OBJECTID,PID,Property_Address,Acres,Legal,Commercial_Building_Market,Residential_Building_Market", 300)
    rows = parse_burleigh_nd_features(feats, warn)[:160]
    if len(rows) < 15:
        raise StructureError("only %d Burleigh County ND parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Vermont Statewide Municipal Vacant Land (VT) ---
VCGI_VT_GIS = "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/FS_VCGI_OPENDATA_Cadastral_VTPARCELS_poly_standardized_parcels_SP_v1/FeatureServer/0/query"
VCGI_VT_URL = "https://vcgi.vermont.gov/"
VT_SKIP = ("PARK", "CEMETERY", "SCHOOL", "WATER", "SEWER", "FIRE", "DUMP", "LANDFILL", "GARAGE", "GRAVEL", "HIGHWAY", "LIBRARY", "BEACH", "POND", "DAM", "BRIDGE", "POOL", "REC ", "RECREATION", "WELL", "PUMP", "PLAYGROUND")


def parse_vcgi_vt_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("IMPRV_LV")):
            continue
        desc = clean(str(a.get("DESCPROP") or ""))
        if any(w in desc.upper() for w in VT_SKIP):
            continue
        span = clean(str(a.get("SPAN") or a.get("OBJECTID") or ""))
        if not span or span in seen:
            continue
        seen.add(span)
        town = clean(str(a.get("TOWN") or "Vermont")).title() or "Vermont"
        addr = clean(str(a.get("E911ADDR") or a.get("LOCAPROP") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACRESGL")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "Vermont Municipal Unimproved Parcel (VCGI Statewide)", VCGI_VT_URL, "vcgi_vt"),
            fact("parcel_number", "SPAN " + span, VCGI_VT_URL),
            fact("price", "Confirm municipal tax-sale or surplus status with %s Town Clerk" % town, VCGI_VT_URL, "vcgi_vt"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, VCGI_VT_URL))
        if desc:
            facts.append(fact("property_class", desc[:140], VCGI_VT_URL))
        title_loc = "%s (%s)" % (addr, span) if addr else ("SPAN " + span)
        row = {
            "id": "vt-vcgi-%s" % slug(span), "source": "vcgi-vt",
            "title": "%s, %s (Vermont municipal vacant land)" % (title_loc, town),
            "state": "VT", "county": town, "locality": town, "apn": span,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": VCGI_VT_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["municipal vacant land", "vermont"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(VCGI_VT_GIS, "SPAN='%s'" % span.replace("'", "''")), "Vermont VCGI Statewide GIS")
        out.append(row)
    return out


def vcgi_vt(fetch, now, warn):
    w = "(OWNER1 LIKE 'TOWN OF %' OR OWNER1 LIKE 'CITY OF %') AND (IMPRV_LV=0 OR IMPRV_LV IS NULL) AND ACRESGL>=0.1 AND ACRESGL<=25"
    feats = _arcgis_query(fetch, VCGI_VT_GIS, w,
                          "OBJECTID,SPAN,TOWN,E911ADDR,LOCAPROP,DESCPROP,ACRESGL,IMPRV_LV", 300)
    rows = parse_vcgi_vt_features(feats, warn)[:160]
    if len(rows) < 20:
        raise StructureError("only %d Vermont municipal vacant parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Montana Statewide County & City Vacant Land (MT) ---
MT_CAD_GIS = "https://services.arcgis.com/qnjIrwR8z5Izc0ij/arcgis/rest/services/Montana_Cadastral_Framework/FeatureServer/1/query"
MT_CAD_URL = "https://dnrc.mt.gov/"


def parse_montana_cad_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("TotalBuildingValue")):
            continue
        pid = clean(str(a.get("PARCELID") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        county = clean(str(a.get("CountyName") or "Montana")).title() or "Montana"
        addr = clean(str(a.get("AddressLine1") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("GISAcres")) or number(a.get("TotalAcres")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        leg = clean(str(a.get("LegalDescriptionShort") or ""))
        facts = [
            fact("availability", "Montana County / Municipal Vacant Land (State Cadastral)", MT_CAD_URL, "montana_cad"),
            fact("parcel_number", pid, MT_CAD_URL),
            fact("price", "Confirm county tax-deed auction or surplus availability with %s County Treasurer" % county, MT_CAD_URL, "montana_cad"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, MT_CAD_URL))
        if leg:
            facts.append(fact("legal_description", leg[:180], MT_CAD_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "mt-cad-%s" % slug(pid), "source": "montana-cad",
            "title": "%s, %s County (Montana public vacant land)" % (title_loc, county),
            "state": "MT", "county": county, "locality": county, "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": MT_CAD_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["public vacant land", "montana"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(MT_CAD_GIS, "PARCELID='%s'" % pid.replace("'", "''")), "Montana State Library Cadastral GIS")
        out.append(row)
    return out


def montana_cad(fetch, now, warn):
    w = "PropType LIKE '%Vacant%' AND (OwnerName LIKE '%COUNTY%' OR OwnerName LIKE '%CITY OF %')"
    feats = _arcgis_query(fetch, MT_CAD_GIS, w,
                          "OBJECTID,PARCELID,CountyName,GISAcres,TotalAcres,AddressLine1,LegalDescriptionShort,TotalBuildingValue", 220, {"orderByFields": "GISAcres DESC"})
    rows = parse_montana_cad_features(feats, warn)[:180]
    if len(rows) < 20:
        raise StructureError("only %d Montana public vacant parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Boise Community Development Parcels (ID) ---
BOISE_ID_GIS = "https://services1.arcgis.com/WHM6qC35aMtyAAlN/arcgis/rest/services/BoiseOwnedProperty/FeatureServer/140/query"
BOISE_ID_URL = "https://www.cityofboise.org/"


def parse_boise_id_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if clean(str(a.get("DEPT") or "")).upper() != "COMDEV":
            continue
        pid = clean(str(a.get("PARCEL") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        parts = [clean(str(a.get(k) or "")) for k in ("PROPADDNUM", "PROPPREDIR", "PROPSTNM", "PROPSTTYPE")]
        addr = " ".join(p for p in parts if p).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("ACRES")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Boise Housing & Community Development Parcel", BOISE_ID_URL, "boise_id"),
            fact("parcel_number", pid, BOISE_ID_URL),
            fact("price", "Disposition / RFP guidelines via City of Boise Community Development", BOISE_ID_URL, "boise_id"),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, BOISE_ID_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "id-boi-%s" % slug(pid), "source": "boise-id",
            "title": "%s, Boise (city development land)" % title_loc,
            "state": "ID", "county": "Ada", "locality": "Boise", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": BOISE_ID_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned land", "idaho"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(BOISE_ID_GIS, "PARCEL='%s'" % pid.replace("'", "''")), "City of Boise ID GIS")
        out.append(row)
    return out


def boise_id(fetch, now, warn):
    feats = _arcgis_query(fetch, BOISE_ID_GIS, "DEPT='COMDEV'",
                          "OBJECTID,PARCEL,ACRES,PROPADDNUM,PROPPREDIR,PROPSTNM,PROPSTTYPE,DEPT", 200)
    rows = parse_boise_id_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Boise ID COMDEV parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Auburn Undeveloped Municipal Land (ME) ---
AUBURN_ME_GIS = "https://services1.arcgis.com/4nU7cbKqLfftauX2/arcgis/rest/services/CityOwned/FeatureServer/0/query"
AUBURN_ME_URL = "https://www.auburnmaine.gov/"
AUBURN_KEEP = ("undeveloped", "commercial land", "industrial land", "urban hslt", "rural hslt")


def parse_auburn_me_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        if number(a.get("BldgValue")):
            continue
        luse = clean(str(a.get("LandUse") or ""))
        if luse.lower() not in AUBURN_KEEP:
            continue
        pid = clean(str(a.get("ParcelID") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("Address") or a.get("Loc") or "")).title()
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = number(a.get("Acreage")) or (rings_acres(rings) if rings else None)
        if acres:
            acres = round(acres, 4)
        facts = [
            fact("availability", "City of Auburn Unimproved Municipal Land", AUBURN_ME_URL, "auburn_me"),
            fact("parcel_number", pid, AUBURN_ME_URL),
            fact("price", "Confirm tax-acquired / surplus sale availability with City of Auburn", AUBURN_ME_URL, "auburn_me"),
            fact("property_class", luse.title(), AUBURN_ME_URL),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % acres, AUBURN_ME_URL))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "me-aub-%s" % slug(pid), "source": "auburn-me",
            "title": "%s, Auburn (Maine municipal vacant land)" % title_loc,
            "state": "ME", "county": "Androscoggin", "locality": "Auburn", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": AUBURN_ME_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["municipal vacant land", "maine"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(AUBURN_ME_GIS, "ParcelID='%s'" % pid.replace("'", "''")), "City of Auburn ME GIS")
        out.append(row)
    return out


def auburn_me(fetch, now, warn):
    feats = _arcgis_query(fetch, AUBURN_ME_GIS, "BldgValue=0 OR BldgValue IS NULL",
                          "OBJECTID,ParcelID,Address,Loc,LandUse,Acreage,BldgValue", 200)
    rows = parse_auburn_me_features(feats, warn)
    if len(rows) < 10:
        raise StructureError("only %d Auburn ME vacant parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Portland Land Bank (ME) ---
PORTLAND_ME_GIS = "https://services5.arcgis.com/Fn6fPZi3nJdsppqD/arcgis/rest/services/City_Owned_2022_v2/FeatureServer/1/query"
PORTLAND_ME_URL = "https://www.portlandmaine.gov/"


def parse_portland_me_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        luse = clean(str(a.get("Land_Use") or ""))
        if luse.upper() not in ("LAND BANKS", "VACANT LAND"):
            continue
        pid = clean(str(a.get("Parcel_ID") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings) if rings else None
        facts = [
            fact("availability", "City of Portland Municipal Land Bank", PORTLAND_ME_URL, "portland_me"),
            fact("parcel_number", pid, PORTLAND_ME_URL),
            fact("price", "Confirm land bank / surplus disposition status on portlandmaine.gov", PORTLAND_ME_URL, "portland_me"),
            fact("property_class", luse.title(), PORTLAND_ME_URL),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, PORTLAND_ME_URL, "gis_area"))
        row = {
            "id": "me-pwm-%s" % slug(pid), "source": "portland-me",
            "title": "Portland ME land bank parcel %s" % pid,
            "state": "ME", "county": "Cumberland", "locality": "Portland", "apn": pid,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": PORTLAND_ME_URL,
            "address": "", "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank vacant lot", "maine"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(PORTLAND_ME_GIS, "OBJECTID=%s" % clean(str(a.get("OBJECTID") or "0"))), "City of Portland ME GIS")
        out.append(row)
    return out


def portland_me(fetch, now, warn):
    feats = _arcgis_query(fetch, PORTLAND_ME_GIS, "Land_Use IN ('LAND BANKS','VACANT LAND')",
                          "OBJECTID,Parcel_ID,Land_Use", 200)
    rows = parse_portland_me_features(feats, warn)
    if len(rows) < 20:
        raise StructureError("only %d Portland ME land bank parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# ------------------------------------------------------------------------------------------- Phase 8: 7 High-Volume Official Agencies (PA Philly, OH Cleveland, TX Dallas, WI Milwaukee, MI Detroit Priced, OH Lucas 2026 Auction, WI Sauk)

def _arcgis_paged(fetch, gis_url, where, out_fields, max_total=1500, page_size=500, extra=None):
    all_feats, offset = [], 0
    while len(all_feats) < max_total:
        need = min(page_size, max_total - len(all_feats))
        ex = dict(extra or {})
        ex["resultOffset"] = str(offset)
        batch = _arcgis_query(fetch, gis_url, where, out_fields, need, extra=ex)
        if not batch:
            break
        all_feats.extend(batch)
        if len(batch) < need:
            break
        offset += len(batch)
    return all_feats


def _sf_to_acres(text):
    s = clean(str(text or ""))
    if not s:
        return None
    m_ac = re.search(r"([\d,]*\.?\d+)\s*(?:acres?|ac\b)", s, re.I)
    if m_ac:
        v = number(m_ac.group(1))
        return round(v, 4) if v else None
    m_sf = re.search(r"([\d,]*\.?\d+)\s*(?:sq\.?\s*ft\.?|sf\b)", s, re.I)
    if m_sf:
        v = number(m_sf.group(1))
        return round(v / 43560.0, 4) if v else None
    return None


# --- Philadelphia Land Bank Vacant Land (PA) ---
PHILLY_LB_GIS = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Vacant_Indicators_Land/FeatureServer/0/query"
PHILLY_LB_URL = "https://phdcphila.org/property-map/"
PHILLY_AVAIL_GIS = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/LAMAAssets/FeatureServer/0/query"
PHILLY_AVAILABLE = ("Owned - Available", "Owned - Available (no construction permitted)",
                    "Owned - Available (not for SY)")


def parse_philly_lb_features(features, availability, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        opa = clean(str(a.get("opa_id") or "")).zfill(9)
        if opa not in availability or opa in seen:
            continue
        seen.add(opa)
        addr = clean(str(a.get("address") or "")).title()
        zoning = clean(str(a.get("zoningbasedistrict") or ""))
        zipcode = clean(str(a.get("zipcode") or ""))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings) if rings else None
        facts = [
            fact("availability", availability[opa], PHILLY_LB_URL),
            fact("parcel_number", opa, PHILLY_LB_URL),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, PHILLY_LB_URL, "gis_area"))
        if zoning:
            facts.append(fact("zoning", zoning, PHILLY_LB_URL))
        if zipcode:
            facts.append(fact("zip_code", zipcode, PHILLY_LB_URL))
        title_loc = "%s (%s)" % (addr, opa) if addr else ("OPA " + opa)
        row = {
            "id": "pa-phl-%s" % slug(opa), "source": "philly-landbank",
            "title": "%s, Philadelphia (Land Bank vacant lot)" % title_loc,
            "state": "PA", "county": "Philadelphia", "locality": "Philadelphia", "apn": opa,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": PHILLY_LB_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank", "vacant lot", "pennsylvania"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(PHILLY_LB_GIS, "opa_id='%s'" % opa.replace("'", "''")), "City of Philadelphia GIS")
        out.append(row)
    return out


def philly_landbank(fetch, now, warn):
    where = "agency = 'PLB' AND status_1 IN (%s)" % quote_list(PHILLY_AVAILABLE)
    count = fetch.json(PHILLY_AVAIL_GIS + "?" + urllib.parse.urlencode({
        "f": "json", "where": where, "returnCountOnly": "true",
    })).get("count")
    if not isinstance(count, int) or not 1 <= count <= 20000:
        raise StructureError("Philadelphia Land Bank availability count is missing or invalid")
    available = _arcgis_paged(fetch, PHILLY_AVAIL_GIS, where, "objectid,opabrt,status_1",
                             max_total=count, page_size=500,
                             extra={"orderByFields": "objectid", "returnGeometry": "false"})
    if len(available) != count:
        raise StructureError("Philadelphia Land Bank inventory was incomplete")
    status = {}
    for feature in available:
        attributes = feature.get("attributes", {})
        opa = clean(str(attributes.get("opabrt") or ""))
        state = attributes.get("status_1")
        if re.fullmatch(r"\d{1,9}", opa) and state in PHILLY_AVAILABLE:
            status[opa.zfill(9)] = state

    rows = []
    ids = sorted(status)
    for start in range(0, len(ids), 64):
        vacant = _arcgis_query(fetch, PHILLY_LB_GIS, "opa_id IN (%s)" % quote_list(ids[start:start + 64]),
                               "objectid,address,opa_id,zoningbasedistrict,zipcode", 500)
        rows.extend(parse_philly_lb_features(vacant, status, warn))
    if not rows:
        raise StructureError("No sale-available Philadelphia parcels matched the official vacant land layer")
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Cleveland Land Bank (OH) ---
CLEVELAND_LB_GIS = "https://services3.arcgis.com/dty2kHktVXHrqO8i/arcgis/rest/services/City_Landbank/FeatureServer/0/query"
CLEVELAND_LB_URL = "https://www.clevelandohio.gov/city-hall/departments/community-development/divisions/land-bank"


def parse_cleveland_lb_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pin = clean(str(a.get("parcelpin") or a.get("OBJECTID") or ""))
        if not pin or pin in seen:
            continue
        seen.add(pin)
        raw_addr = clean(str(a.get("par_addr_all") or ""))
        addr = raw_addr.split(",")[0].strip().title() if raw_addr else ""
        if addr.startswith("0 "):
            addr = addr[2:].strip()
        lb_type = clean(str(a.get("cityLandBankType") or "Vacant Land"))
        rings = (f.get("geometry") or {}).get("rings") or []
        acres = rings_acres(rings) if rings else None
        facts = [
            fact("availability", "City of Cleveland Land Bank (%s)" % lb_type, CLEVELAND_LB_URL, "cleveland_lb"),
            fact("parcel_number", pin, CLEVELAND_LB_URL),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres (GIS polygon estimate)" % acres, CLEVELAND_LB_URL, "gis_area"))
        front = number(a.get("total_legal_front"))
        if front:
            facts.append(fact("frontage", "%g ft" % round(front, 1), CLEVELAND_LB_URL))
        title_loc = "%s (%s)" % (addr, pin) if addr else ("PIN " + pin)
        row = {
            "id": "oh-cle-%s" % slug(pin), "source": "cleveland-landbank",
            "title": "%s, Cleveland (Land Bank lot)" % title_loc,
            "state": "OH", "county": "Cuyahoga", "locality": "Cleveland", "apn": pin,
            "acres": acres, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": CLEVELAND_LB_URL,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["land bank", "vacant lot", "ohio"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(CLEVELAND_LB_GIS, "parcelpin='%s'" % pin.replace("'", "''")), "City of Cleveland GIS")
        out.append(row)
    return out


def cleveland_landbank(fetch, now, warn):
    feats = _arcgis_paged(fetch, CLEVELAND_LB_GIS, "cityLandBankType IN ('Residential','Commercial','Industrial')",
                          "OBJECTID,parcelpin,par_addr_all,total_legal_front,total_square_ft,cityLandBankType",
                          max_total=1600, page_size=500, extra={"orderByFields": "total_square_ft DESC"})
    rows = parse_cleveland_lb_features(feats, warn)
    if len(rows) < 200:
        raise StructureError("only %d Cleveland Land Bank parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Dallas Land Bank Vacant Lots (TX) ---
DALLAS_LB_GIS = "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/Land_Bank_Potential_Properties/FeatureServer/0/query"
DALLAS_LB_URL = "https://dallascityhall.com/departments/housing-neighborhood-revitalization/Pages/land-bank.aspx"


def parse_dallas_lb_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        acct = clean(str(a.get("AccountID") or a.get("OBJECTID") or ""))
        if not acct or acct in seen:
            continue
        seen.add(acct)
        num = clean(str(a.get("SiteAddrNu") or ""))
        st = clean(str(a.get("SiteStreet") or ""))
        addr = (" ".join(x for x in (num, st) if x)).title()
        pclass = clean(str(a.get("PropClass") or "Vacant Land"))
        rsa = clean(str(a.get("RSA_Name") or ""))
        geom = f.get("geometry") or {}
        lon = geom.get("x")
        lat = geom.get("y")
        facts = [
            fact("availability", "City of Dallas Land Bank vacant lot", DALLAS_LB_URL, "dallas_lb"),
            fact("parcel_number", acct, DALLAS_LB_URL),
            fact("property_class", pclass, DALLAS_LB_URL),
        ]
        if rsa:
            facts.append(fact("district", rsa, DALLAS_LB_URL))
        title_loc = "%s (%s)" % (addr, acct) if addr else ("Account " + acct)
        row = {
            "id": "tx-dal-%s" % slug(acct), "source": "dallas-landbank",
            "title": "%s, Dallas (Land Bank vacant lot)" % title_loc,
            "state": "TX", "county": "Dallas", "locality": "Dallas", "apn": acct,
            "acres": None, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": DALLAS_LB_URL,
            "address": addr,
            "lat": round(float(lat), 6) if lat is not None else None,
            "lon": round(float(lon), 6) if lon is not None else None,
            "geometry": None, "facts": facts,
            "tags": ["land bank", "vacant lot", "texas"],
        }
        out.append(row)
    return out


def dallas_landbank(fetch, now, warn):
    feats = _arcgis_paged(fetch, DALLAS_LB_GIS, "BldgClass='LAND ONLY'",
                          "OBJECTID,AccountID,SiteAddrNu,SiteStreet,PropClass,RSA_Name",
                          max_total=1000, page_size=500)
    rows = parse_dallas_lb_features(feats, warn)
    if len(rows) < 100:
        raise StructureError("only %d Dallas Land Bank parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Milwaukee DCD Advertised Vacant Lots (WI) ---
MILWAUKEE_GIS = "https://milwaukeemaps.milwaukee.gov/arcgis/rest/services/StrongNeighborhood/StrongNeighborhood/MapServer/1/query"
MILWAUKEE_URL = "https://city.milwaukee.gov/DCD/CityRealEstate"


def parse_milwaukee_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        taxkey = clean(str(a.get("TAXKEY") or a.get("OBJECTID") or ""))
        if not taxkey or taxkey in seen:
            continue
        seen.add(taxkey)
        addr = clean(str(a.get("COMBINEDADDRESS") or "")).title()
        zoning = clean(str(a.get("ZONING") or ""))
        zipcode = clean(str(a.get("ZIPCODE") or ""))
        geom = f.get("geometry") or {}
        lon = geom.get("x")
        lat = geom.get("y")
        facts = [
            fact("availability", "City of Milwaukee Advertised Vacant Lot For Sale", MILWAUKEE_URL, "milwaukee_vac"),
            fact("parcel_number", taxkey, MILWAUKEE_URL),
        ]
        if zoning:
            facts.append(fact("zoning", zoning, MILWAUKEE_URL))
        if zipcode:
            facts.append(fact("zip_code", zipcode, MILWAUKEE_URL))
        title_loc = "%s (%s)" % (addr, taxkey) if addr else ("TaxKey " + taxkey)
        row = {
            "id": "wi-mke-%s" % slug(taxkey), "source": "milwaukee-vacant",
            "title": "%s, Milwaukee (City vacant lot for sale)" % title_loc,
            "state": "WI", "county": "Milwaukee", "locality": "Milwaukee", "apn": taxkey,
            "acres": None, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": MILWAUKEE_URL,
            "address": addr,
            "lat": round(float(lat), 6) if lat is not None else None,
            "lon": round(float(lon), 6) if lon is not None else None,
            "geometry": None, "facts": facts,
            "tags": ["city surplus", "vacant lot", "wisconsin"],
        }
        out.append(row)
    return out


def milwaukee_vacant(fetch, now, warn):
    feats = _arcgis_paged(fetch, MILWAUKEE_GIS,
                          "ACTIVE=1 AND DISPOSITIONSTATUS='Advertised' AND DISPOSITIONSTRATEGY='Dispose' AND PROPERTYTYPE='Vacant Lot'",
                          "OBJECTID,TAXKEY,COMBINEDADDRESS,ZONING,ZIPCODE",
                          max_total=800, page_size=500)
    rows = parse_milwaukee_features(feats, warn)
    if len(rows) < 50:
        raise StructureError("only %d Milwaukee advertised vacant lots" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- City of Detroit Priced Commercial & Vacant Land For Sale (MI) ---
DETROIT_COMM_GIS = "https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/Commercial_Properties_for_Sale/FeatureServer/0/query"
DETROIT_COMM_URL = "https://detroitmi.gov/departments/housing-and-revitalization-department/commercial-real-estate"


def parse_detroit_comm_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        lid = clean(str(a.get("id") or a.get("ObjectId") or ""))
        if not lid or lid in seen:
            continue
        seen.add(lid)
        addr = clean(str(a.get("address") or "")).title()
        title_raw = clean(str(a.get("title") or ""))
        size_raw = clean(str(a.get("size") or ""))
        price = number(a.get("price"))
        acres = _sf_to_acres(size_raw)
        geom = f.get("geometry") or {}
        lon = geom.get("x")
        lat = geom.get("y")
        facts = [
            fact("availability", "City of Detroit Vacant Land For Sale", DETROIT_COMM_URL, "detroit_comm"),
            fact("listing_id", lid, DETROIT_COMM_URL),
        ]
        if price:
            facts.append(fact("price", "Asking price $%s" % "{:,.0f}".format(price), DETROIT_COMM_URL, "detroit_comm"))
        if size_raw:
            facts.append(fact("lot_size", size_raw, DETROIT_COMM_URL))
        title_loc = "%s — %s" % (addr, title_raw) if (addr and title_raw) else (addr or title_raw or ("Detroit Lot " + lid))
        row = {
            "id": "mi-detc-%s" % slug(lid), "source": "detroit-commercial-land",
            "title": "%s, Detroit (Priced vacant land)" % title_loc[:90],
            "state": "MI", "county": "Wayne", "locality": "Detroit", "apn": lid,
            "acres": acres, "price": round(price, 2) if price else None,
            "price_kind": "cash" if price else "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": DETROIT_COMM_URL,
            "address": addr,
            "lat": round(float(lat), 6) if lat is not None else None,
            "lon": round(float(lon), 6) if lon is not None else None,
            "geometry": None, "facts": facts,
            "tags": ["buy it now", "vacant land", "michigan"],
        }
        out.append(row)
    return out


def detroit_commercial_land(fetch, now, warn):
    feats = _arcgis_query(fetch, DETROIT_COMM_GIS, "property_type='Vacant Land'",
                          "ObjectId,id,address,title,size,price,property_type", 200)
    rows = parse_detroit_comm_features(feats, warn)
    if len(rows) < 10:
        raise StructureError("only %d Detroit priced vacant land parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Lucas County Auditor 2026 Forfeited Land Sale (OH) ---
LUCAS_FORF_GIS = "https://services3.arcgis.com/T8dczfwPixv79EgZ/arcgis/rest/services/Forfeited_Land_Sale_2026/FeatureServer/0/query"
LUCAS_FORF_URL = "https://co.lucas.oh.us/262/Forfeited-Land-Sale"


def parse_lucas_forf_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        parid = clean(str(a.get("parid") or a.get("assessor_num") or a.get("objectid") or ""))
        if not parid or parid in seen:
            continue
        seen.add(parid)
        raw_addr = clean(str(a.get("property_address") or ""))
        addr = raw_addr.split(",")[0].strip().title() if raw_addr else ""
        taxes = number(a.get("taxesowed"))
        zoning = clean(str(a.get("zoning") or ""))
        desc = clean(str(a.get("description") or ""))
        geom = f.get("geometry") or {}
        lon = geom.get("x")
        lat = geom.get("y")
        facts = [
            fact("availability", "Lucas County 2026 Forfeited Land Sale", LUCAS_FORF_URL, "lucas_forf_2026"),
            fact("parcel_number", parid, LUCAS_FORF_URL),
        ]
        if taxes:
            facts.append(fact("price", "Delinquent tax / opening bid $%s" % "{:,.2f}".format(taxes), LUCAS_FORF_URL, "lucas_forf_2026"))
        if zoning:
            facts.append(fact("zoning", zoning, LUCAS_FORF_URL))
        if desc:
            facts.append(fact("land_class", desc, LUCAS_FORF_URL))
        title_loc = "%s (%s)" % (addr, parid) if addr else ("Parcel " + parid)
        row = {
            "id": "oh-lucf26-%s" % slug(parid), "source": "lucas-forfeited-2026",
            "title": "%s, Toledo (2026 Forfeited Land Sale)" % title_loc,
            "state": "OH", "county": "Lucas", "locality": "Toledo", "apn": parid,
            "acres": None, "price": round(taxes, 2) if taxes else None,
            "price_kind": "min_bid" if taxes else "none", "offering": "auction",
            "status": "auction_terms", "deadline": None, "url": LUCAS_FORF_URL,
            "address": addr,
            "lat": round(float(lat), 6) if lat is not None else None,
            "lon": round(float(lon), 6) if lon is not None else None,
            "geometry": None, "facts": facts,
            "tags": ["tax sale", "forfeited land", "ohio"],
        }
        out.append(row)
    return out


def lucas_forfeited_2026(fetch, now, warn):
    feats = _arcgis_query(fetch, LUCAS_FORF_GIS, "1=1",
                          "objectid,parid,assessor_num,property_address,zoning,description,taxesowed", 200)
    rows = parse_lucas_forf_features(feats, warn)
    if len(rows) < 5:
        raise StructureError("only %d Lucas 2026 forfeited parcels" % len(rows))
    return rows, {"complete": True, "upstream_total": len(rows)}


# --- Sauk County Tax-Forfeited Parcels For Sale (WI) ---
SAUK_WI_GIS = "https://gis.co.sauk.wi.us/arcgis/rest/services/Sauk/TaxParcelsForSale/MapServer/0/query"
SAUK_WI_URL = "https://www.co.sauk.wi.us/treasurer/tax-deed-sales"


def parse_sauk_wi_features(features, warn):
    out, seen = [], set()
    for f in features:
        a = f.get("attributes") or {}
        pid = clean(str(a.get("PARCELID") or a.get("OBJECTID") or ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = clean(str(a.get("SITEADDRESS") or "")).title()
        if re.match(r"^p\.?\s*o\.?\s*box\b", addr, re.I):
            addr = ""
        acres = number(a.get("TOTALACREAGE"))
        url = clean(str(a.get("URL") or ""))
        if not url.startswith("https://") or "co.sauk.wi.us" not in url:
            url = SAUK_WI_URL
        rings = (f.get("geometry") or {}).get("rings") or []
        if not acres and rings:
            acres = rings_acres(rings)
        facts = [
            fact("availability", "Sauk County Tax-Forfeited Land (Offer to Purchase)", url, "sauk_wi"),
            fact("parcel_number", pid, url),
        ]
        if acres:
            facts.append(fact("acreage", "%g acres" % round(acres, 3), url))
        title_loc = "%s (%s)" % (addr, pid) if addr else ("Parcel " + pid)
        row = {
            "id": "wi-sauk-%s" % slug(pid), "source": "sauk-county-wi",
            "title": "%s, Sauk County (Wisconsin tax-forfeited land)" % title_loc,
            "state": "WI", "county": "Sauk", "locality": "Baraboo", "apn": pid,
            "acres": round(acres, 4) if acres else None, "price": None, "price_kind": "none",
            "offering": "sale", "status": "listed", "deadline": None, "url": url,
            "address": addr, "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["tax forfeited", "rural land", "wisconsin"],
        }
        if rings:
            apply_geometry(row, rings, one_parcel_url(SAUK_WI_GIS, "PARCELID='%s'" % pid.replace("'", "''")), "Sauk County WI GIS")
        out.append(row)
    return out


def sauk_county_wi(fetch, now, warn):
    feats = _arcgis_paged(fetch, SAUK_WI_GIS, "1=1",
                          "OBJECTID,PARCELID,SITEADDRESS,URL,TOTALACREAGE", max_total=500, page_size=200)
    rows = parse_sauk_wi_features(feats, warn)
    if not rows:
        raise StructureError("no Sauk County WI parcels")
    return rows, {"complete": True, "upstream_total": len(rows)}


# Hoke County publishes a current, parcel-specific minimum-bid table for its surplus lots.
HOKE_NC_URL = "https://hokecounty.net/474/Surplus-Properties-for-Sale"


def parse_hoke_surplus(page, now, warn):
    for table in re.findall(r"<table\b[^>]*>(.*?)</table>", page, re.I | re.S):
        headings = clean(table)
        if "Approximate Acreage" in headings and "Minimum Bid" in headings and "Parcel Number" in headings:
            break
    else:
        raise StructureError("Hoke County surplus bid table is missing")

    listings = []
    for line in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.I | re.S):
        fields = [clean(cell) for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", line, re.I | re.S)]
        if len(fields) != 7:
            continue
        _, pin, area, address, minimum, _, upset = fields
        price = number(minimum)
        if not re.fullmatch(r"\d{5}-\d{2}-\d{2}-\d{3}", pin) or not price:
            continue
        if re.search(r"\b(closed|sold|pending|withdrawn)\b", upset, re.I):
            continue
        # The county labels these rows as vacant land by acreage or as a lot.
        if not re.fullmatch(r"(?:\d*\.?\d+|Lot)", area, re.I):
            continue
        acres = number(area)
        listings.append({
            "id": "nc-hoke-%s" % slug(pin), "source": "hoke-county-nc", "state": "NC",
            "county": "Hoke", "locality": "", "address": address, "apn": pin,
            "title": "%s (%s), Hoke County surplus land" % (address or "Parcel", pin),
            "acres": acres, "price": price, "price_kind": "min_bid",
            "offering": "auction", "status": "auction_terms", "deadline": None,
            "url": HOKE_NC_URL, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("minimum_bid", "$%s" % "{:,.2f}".format(price), HOKE_NC_URL),
                      fact("availability", "Listed on the county's surplus properties for sale table", HOKE_NC_URL)],
            "tags": ["surplus land", "upset bid", "north carolina"],
        })
    return listings


def hoke_surplus(fetch, now, warn):
    rows = parse_hoke_surplus(fetch.text(HOKE_NC_URL), now, warn)
    return rows, {"complete": True, "upstream_total": len(rows)}


WSDOT_URL = "https://wsdot.wa.gov/business-wsdot/real-estate-services/current-sales-and-auctions"


def parse_wsdot_index(page):
    section = re.search(r"<h3[^>]*>Properties available on a first come, first serve basis</h3>(.*?)(?:<h2|</article)", page, re.I | re.S)
    if not section:
        raise StructureError("WSDOT current sale lists not found")
    entries = []
    for county, block in re.findall(r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|$)", section[1], re.I | re.S):
        name = clean(county)
        if not name.endswith(" County"):
            continue
        for link, label in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S):
            reference = re.fullmatch(r"Parcel number:\s+([0-9-]+(?:\s+&\s+[0-9-]+)?)", clean(label))
            url = urllib.parse.urljoin(WSDOT_URL, html.unescape(link))
            if reference and urllib.parse.urlsplit(url).netloc == "wsdot.wa.gov":
                entries.append((name.removesuffix(" County"), reference[1], url))
    return entries


def parse_wsdot_property(page, county, reference, url):
    fields = {clean(label).lower(): clean(value) for label, value in
              re.findall(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|</article|$)", page, re.I | re.S)}
    if not re.match(r"^(none\b|no improvements\b)", fields.get("improvements", ""), re.I):
        return None
    price = number(fields.get("minimum bid"))
    if not price:
        return None
    location = fields.get("location and size", "")
    size = re.search(r"(\d[\d,.]*)\s*(?:[+±]\s*/?\s*[-−]?\s*)?acres?\b", location, re.I)
    acres = number(size[1]) if size else None
    return {
        "id": "wa-wsdot-%s" % slug(reference), "source": "wsdot-surplus", "state": "WA", "county": county,
        "locality": "", "address": "", "apn": "", "title": "WSDOT parcel %s in %s County" % (reference, county),
        "acres": acres, "price": price, "price_kind": "application", "offering": "sale", "status": "listed",
        "deadline": None, "url": url, "lat": None, "lon": None, "geometry": None,
        "facts": [fact("agency_parcel_number", reference, url),
                  fact("minimum_offer", "$%s" % "{:,.2f}".format(price), url),
                  fact("availability", "Listed by WSDOT for first-come, first-served purchase", WSDOT_URL),
                  fact("improvements", "None listed by WSDOT", url)],
        "tags": ["surplus land", "right of way", "washington"],
    }


def wsdot_surplus(fetch, now, warn):
    entries = parse_wsdot_index(fetch.text(WSDOT_URL))
    rows = [parse_wsdot_property(fetch.text(url), county, reference, url) for county, reference, url in entries]
    rows = [row for row in rows if row]
    return rows, {"complete": True, "upstream_total": len(entries)}


ITASCA_URL = "https://www.itascacountymn.gov/304/Real-Estate"


def pdf_text(fetch, url, *, extraction_mode="layout"):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(fetch.bytes(url)))
    if not 1 <= len(reader.pages) <= 60:
        raise StructureError("Unexpected page count for county sale PDF")
    return "\n".join(page.extract_text(extraction_mode=extraction_mode) for page in reader.pages)


def find_itasca_report(page):
    for link, label in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        if clean(label).startswith("OTC General Listing"):
            url = urllib.parse.urljoin(ITASCA_URL, html.unescape(link))
            if urllib.parse.urlsplit(url).netloc == "www.itascacountymn.gov":
                return url
    raise StructureError("Itasca County's over-the-counter listing link is missing")


def parse_itasca_otc(text, url, now, warn):
    if "AVAILABLE OVER-THE-COUNTER" not in text.upper() or not re.search(r"^\s*UNIMPROVED\s*$", text, re.M):
        raise StructureError("Itasca County report lacks its unimproved sale section")
    body = re.split(r"^\s*UNIMPROVED\s*$", text, maxsplit=1, flags=re.M)[1]
    body = re.split(r"^Tracts are available", body, maxsplit=1, flags=re.M)[0]
    rows = []
    pattern = (r"^\s*(?:\d+[#*+^]*\s{2,})?(\d[\d.]*)\s{2,}(\d{2}-\d{3}-\d{4})\s{2,}.*"
               r"\$([\d,]+\.\d{2})\s*$")
    for match in re.finditer(pattern, body, re.M):
        acres, pin, amount = match.groups()
        price = number(amount)
        if not price:
            continue
        rows.append({
            "id": "mn-itasca-%s" % slug(pin), "source": "itasca-county-mn",
            "state": "MN", "county": "Itasca", "locality": "", "address": "", "apn": pin,
            "title": "Parcel %s, Itasca County over-the-counter land" % pin, "acres": number(acres),
            "price": price, "price_kind": "application", "offering": "sale", "status": "listed", "deadline": None,
            "url": url, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("minimum_offer", "$%s" % "{:,.2f}".format(price), url),
                      fact("sale_program", "First-come, first-served at or above the county's published amount", url)],
            "tags": ["tax forfeited", "over the counter", "minnesota"],
        })
    return rows


def itasca_otc(fetch, now, warn):
    url = find_itasca_report(fetch.text(ITASCA_URL))
    rows = parse_itasca_otc(pdf_text(fetch, url), url, now, warn)
    return rows, {"complete": True, "upstream_total": len(rows)}


# Valencia County publishes its application inventory through its parcel map.
VALENCIA_BUY = "https://co.valencia.nm.us/DocumentCenter/View/29749/Purchasing-Processpdf?bidId="
VALENCIA_MAP = "https://arcgisce2.co.valencia.nm.us/parcelmap/"
VALENCIA_QUERY = "https://arcgisce2.co.valencia.nm.us/arcgis/rest/services/OnlineMap/MapServer/0/query"
VALENCIA_SUBDIVISIONS = {
    "RIO DEL ORO", "RIO GRANDE ESTATES", "MEADOW LAKE SUBDIVISION", "CANYON DEL RIO", "HIGHLAND MEADOWS",
    "MANZANO VIEW ESTATES", "LAS MARAVILLAS", "EL MONTE ESTATES", "LA PONDEROSA FARMS", "RANCHO RIO GRANDE",
}
NM_PT_URL = "https://www.tax.newmexico.gov/businesses/property-tax-overview/delinquent-property-tax-auctions/"
STLOUIS_MN_URL = ("https://www.stlouiscountymn.gov/departments-a-z/land-minerals/sales-and-contracts/"
                  "tax-forfeited-land-sales")


def valencia_lot_listing(feature, source, url, bid=None, deadline=None):
    a = feature.get("attributes") or {}
    upc = str(a.get("UPC") or "").strip()
    if not re.fullmatch(r"\d{19}", upc) or a.get("IMPACT") != 0:
        return None
    account = str(a.get("AccountNum") or "")
    if not re.fullmatch(r"R\d{5,9}", account):
        return None
    rings = (feature.get("geometry") or {}).get("rings") or []
    acres = rings_acres(rings)
    if not acres:
        return None
    facts = [fact("parcel_number", upc, VALENCIA_MAP), fact("county_account", account, VALENCIA_MAP),
             fact("acreage", "%g acres (county GIS outline)" % acres, VALENCIA_MAP),
             fact("assessment", "No improvement value reported in the county parcel layer", VALENCIA_MAP)]
    is_county = source == "valencia-county-land"
    if is_county:
        subd = str(a.get("Subdivisio") or "").strip().upper()
        lot = str(a.get("Lot") or "").strip()
        situs = str(a.get("Situs") or "").strip()
        if subd not in VALENCIA_SUBDIVISIONS or not lot or re.match(r"^[1-9]\d*\s", situs) or acres >= 1:
            return None
        facts.append(fact("sale_program", "Purchase inquiry through the Valencia County Manager. Confirm current availability and the parcel-specific price.", url))
    else:
        facts.append(fact("minimum_bid", "$%s" % "{:,.2f}".format(bid), url))
        facts.append(fact("sale_program", "State delinquent property tax auction. Confirm the lot remains in the sale before bidding.", url))
    row = {
        "id": ("nm-vc-" if is_county else "nm-pt-va-") + upc, "source": source, "state": "NM",
        "county": "Valencia", "locality": "", "address": "", "apn": upc,
        "title": "Parcel %s, Valencia County %s" % (account, "land" if is_county else "tax auction"),
        "acres": acres, "price": bid, "price_kind": "none" if is_county else "min_bid",
        "offering": "sale" if is_county else "auction", "status": "listed" if is_county else "auction_open",
        "deadline": deadline, "url": url, "lat": None, "lon": None, "geometry": None,
        "facts": facts, "tags": ["county purchase application"] if is_county else ["state tax auction"],
    }
    apply_geometry(row, rings, VALENCIA_MAP, "Valencia County")
    if rings and row["facts"][-1]["topic"] == "parcel_outline":
        row["facts"][-1]["url"] = VALENCIA_MAP
    return row


def valencia_county_land(fetch, now, warn):
    # Recheck the county's published invitation as well as the parcel data.
    if not fetch.bytes(VALENCIA_BUY).startswith(b"%PDF-"):
        raise StructureError("Valencia's land purchase instructions are unavailable")
    candidates = _arcgis_paged(fetch, VALENCIA_QUERY, "UPPER(Owner) = 'COUNTY OF VALENCIA' AND IMPACT=0",
                              "OBJECTID,UPC,AccountNum,IMPACT,Subdivisio,Lot,Situs", max_total=2000,
                              extra={"orderByFields": "OBJECTID ASC"})
    if not candidates or len(candidates) >= 2000:
        raise StructureError("Valencia County's purchase inventory returned an implausible number of parcels")
    rows = [row for f in candidates if (row := valencia_lot_listing(f, "valencia-county-land", VALENCIA_BUY))]
    return rows, {"complete": True, "upstream_total": len(candidates)}


def parse_valencia_auction(text, now):
    from zoneinfo import ZoneInfo

    parsed_date = re.search(r"^\s*DATE:\s*\w+,\s*(\w+ \d{1,2}, \d{4})\s*$", text, re.M)
    parsed_time = re.search(r"^\s*TIME:\s*(\d{1,2}:\d\d\s*[AP]M)\s*$", text, re.M)
    if not parsed_date or not parsed_time or "VALENCIA COUNTY" not in text[:500].upper():
        raise StructureError("Valencia County tax auction notice lost its date or terms")
    when = datetime.datetime.strptime(parsed_date[1] + " " + parsed_time[1], "%B %d, %Y %I:%M %p").replace(
        tzinfo=ZoneInfo("America/Denver"))
    if when <= now:
        return {}, None
    bids = {}
    for parcel in re.split(r"(?m)^\s*Item #\d+\b", text)[1:]:
        upc = re.search(r"(?m)^\s*UPC:\s*(\d{19})\s*$", parcel)
        price = re.search(r"(?m)^\s*Minimum Bid:\s*\$([\d,]+\.\d{2})\s*$", parcel)
        if upc and price and not re.search(r"\bMH\s*#|\bMOBILE HOME\b", parcel, re.I):
            amount = number(price[1])
            if amount:
                bids[upc[1]] = amount
    if not bids:
        raise StructureError("No qualifying UPCs or minimum bids parsed from the future Valencia notice")
    return bids, when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nm_valencia_tax_sale(fetch, now, warn):
    page = fetch.text(NM_PT_URL)
    links = []
    for href, label in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        if clean(label) == "Valencia County" and "AuctionAdvertisement" in href:
            url = urllib.parse.urljoin(NM_PT_URL, html.unescape(href))
            if urllib.parse.urlsplit(url).netloc == "www.tax.newmexico.gov" and url.endswith(".pdf"):
                links.append(url)
    rows = []
    for url in dict.fromkeys(links):
        bids, deadline = parse_valencia_auction(pdf_text(fetch, url), now)
        pins = sorted(bids)
        for start in range(0, len(pins), 35):
            where = "IMPACT=0 AND UPC IN (" + quote_list(pins[start:start + 35]) + ")"
            for feature in _arcgis_query(fetch, VALENCIA_QUERY, where, "UPC,AccountNum,IMPACT"):
                upc = str(feature.get("attributes", {}).get("UPC", ""))
                if upc not in bids:
                    continue
                row = valencia_lot_listing(feature, "nm-valencia-tax-auction", url, bids[upc], deadline)
                if row:
                    rows.append(row)
    return rows, {"complete": True, "upstream_total": len(rows)}


def parse_stlouis_mn_book(text, url):
    if "purchase\n" not in text.lower() or "over the counter" not in text.lower():
        raise StructureError("St. Louis County report is missing its over-the-counter terms")
    headers = list(re.finditer(
        r"(?m)^\s*Tract\s+(\d+)\s{2,}([^\n]+?)\s{2,}([0-9]{3}-[0-9]{4}-[0-9]{5}(?:,\s*\d{5})*)"
        r"\s{2,}\$([\d,]+\.\d{2})\s+±\s*([\d.]+)\s+acres?\s+(C\d{8})\s*$", text,
    ))
    if not headers:
        raise StructureError("St. Louis County report has no recognizable available tracts")
    rows = []
    for i, match in enumerate(headers):
        tract, place, pin, price, acres, file_no = match.groups()
        # County marks sold entries inline, between their header and value table.
        body = text[match.end():headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        amounts = re.search(r"(?m)^\s*Improvements\s+\$0\.00\s*$", body)
        total = re.search(r"(?m)^\s*Total\s+\$([\d,]+\.\d{2})\s*$", body)
        if not amounts or not total or price != total[1] or re.search(
            r"(?im)^\s*(?:SOLD|PENDING(?: SALE)?|WITHDRAWN|REMOVED|NOT AVAILABLE)\s*$", body,
        ):
            continue
        if re.search(r"\bhas a water tower\b|\bhas an existing (?:building|house|cabin|garage)\b", body, re.I):
            continue
        amount, area = number(price), number(acres)
        if not amount or not area:
            continue
        rows.append({
            "id": "mn-stl-otc-" + file_no.lower(), "source": "stlouis-county-mn", "state": "MN",
            "county": "St. Louis", "locality": place.strip().title(), "address": "", "apn": pin,
            "title": "St. Louis County tax-forfeited land %s" % file_no, "acres": area,
            "price": amount, "price_kind": "cash", "offering": "sale", "status": "listed",
            "deadline": None, "url": url, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("parcel_number", pin, url), fact("agency_site_id", file_no, url),
                      fact("sale_program", "Published county over-the-counter price. Confirm availability and settlement fees.", url)],
            "tags": ["tax forfeited", "over the counter"],
        })
    return rows


def stlouis_mn_land(fetch, now, warn):
    page = fetch.text(STLOUIS_MN_URL)
    for href, label in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        if clean(label) == "Available Property Booklet":
            url = urllib.parse.urljoin(STLOUIS_MN_URL, html.unescape(href))
            if urllib.parse.urlsplit(url).netloc == "www.stlouiscountymn.gov":
                rows = parse_stlouis_mn_book(pdf_text(fetch, url), url)
                return rows, {"complete": True, "upstream_total": len(rows)}
    raise StructureError("St. Louis County available property booklet link missing")


FNSB_SALE = "https://www.fnsb.gov/1295/West-Chatanika-River-Recreation-Subdivis"


def parse_fnsb_chatanika(page):
    if "Available lots are sold at their established fair market value" not in clean(page):
        raise StructureError("Fairbanks North Star Borough did not confirm the over-the-counter sale price rule")
    rows = []
    for href, label in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        match = re.fullmatch(r"WCRR Lot (\d+) \(FMV \$([\d,]+)\)", clean(label))
        url = urllib.parse.urljoin(FNSB_SALE, html.unescape(href))
        if not match or urllib.parse.urlsplit(url).netloc != "www.fnsb.gov":
            continue
        lot, bid = match.groups()
        price = number(bid)
        if not price:
            continue
        rows.append({
            "id": "ak-fnsb-chatanika-" + lot, "source": "fnsb-chatanika-otc", "state": "AK",
            "county": "Fairbanks North Star", "locality": "West Chatanika River", "address": "", "apn": "",
            "title": "West Chatanika River Recreational Subdivision lot " + lot,
            "acres": None, "price": price, "price_kind": "cash", "offering": "sale", "status": "listed",
            "deadline": None, "url": url, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("parcel_number", "Subdivision lot " + lot, url), fact("price", "$" + bid, url),
                      fact("sale_program", "First-come, first-served at the published fair market value. Borough processing fees are separate.", FNSB_SALE)],
            "tags": ["recreation", "borough land", "over the counter"],
        })
    if not rows:
        raise StructureError("Fairbanks North Star Borough's current lot sheets were not found")
    return rows


def fnsb_chatanika(fetch, now, warn):
    rows = parse_fnsb_chatanika(fetch.text(FNSB_SALE))
    return rows, {"complete": True, "upstream_total": len(rows)}


URLS.update({
    "stl_inventory": STL + "LRA_INVENTORY.csv",
    "stl_available": STL + "LRA_INVENTORY_AVAILABLE.csv",
    "dlba_gis": "https://data.detroitmi.gov/datasets/dlba-owned-properties",
    "kc_dataset": KC_DATASET,
    "chi_dataset": CHI_DATASET,
    "pgh_dataset": PGH_DATASET,
    "lou_gis": LOU_URL,
    "lucas_gis": LUCAS_URL,
})

SSLBDA_URL = "https://www.southsuburbanlandbank.org/property-listings-land"
SSLBDA_LIST = "https://sslbda.pps.land/sslbda-vacant-land/"


def parse_south_suburban(page):
    table = re.search(r'<table\b[^>]*\bid="parcel-list-table"[^>]*>(.*?)</table>', page, re.S)
    if not table or "Parcel Number" not in table[1] or "Property Type" not in table[1]:
        raise StructureError("South Suburban Land Bank sale table changed")
    marker_json = re.search(r"var markersOnMap\s*=\s*(\[.*?\]);", page, re.S)
    markers = {m["ppn"]: m["LatLng"] for m in json.loads(marker_json[1])} if marker_json else {}
    rows, seen = [], set()
    for entry in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table[1], re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", entry, re.S)
        if len(cells) != 6:
            continue
        pid, address, city, kind, status, _ = map(clean, cells)
        if status != "Available" or kind not in ("Residential Lot", "Commercial Lot"):
            continue
        if not re.fullmatch(r"\d{2}-\d{2}(?:-\d{2})?-\d{3}-\d{3}-\d{4}", pid) or pid in seen or not city:
            continue
        if re.search(r"\b(?:apt|unit|suite)\.?\s+\w", address, re.I):
            continue
        seen.add(pid)
        record = urllib.parse.urljoin(SSLBDA_LIST, "/sslbda-property-detail/?parcel_id=" + pid)
        point = markers.get(pid, {})
        lat, lon = point.get("lat"), point.get("lng")
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                and 37 < lat < 43 and -92 < lon < -87):
            lat = lon = None
        city = city.title()
        rows.append({
            "id": "il-sslbda-" + slug(pid), "source": "south-suburban-landbank",
            "title": "%s, %s (%s)" % (address or "Parcel " + pid, city, kind.lower()),
            "state": "IL", "county": "", "locality": city, "apn": pid,
            "acres": None, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": SSLBDA_URL, "address": address,
            "lat": lat, "lon": lon, "geometry": None,
            "facts": [fact("availability", "Available through the Land Bank", record),
                      fact("property_class", kind, record), fact("parcel_number", pid, record)],
            "tags": ["land bank vacant lot", "application required"],
        })
    return rows


def south_suburban_landbank(fetch, now, warn):
    index = fetch.text(SSLBDA_URL)
    if not re.search(r'<iframe\b[^>]*\bsrc=["\']' + re.escape(SSLBDA_LIST) + r'["\']', index, re.I):
        raise StructureError("South Suburban Land Bank no longer links to the sale table")
    rows = parse_south_suburban(fetch.text(SSLBDA_LIST))
    return rows, {"complete": True, "upstream_total": len(rows)}


NEWBURGH_URL = "https://www.newburghcommunitylandbank.org/properties"


def parse_newburgh_sale(page):
    section = re.search(
        r"<h2\b[^>]*>\s*currently available for sale\s*:?\s*</h2>(.*?)<h2\b[^>]*>\s*not for sale at this time",
        page, re.I | re.S,
    )
    if not section:
        raise StructureError("Newburgh's available property section changed")
    rows, seen = [], set()
    for item in re.findall(r"<p\b[^>]*>(.*?)</p>", section[1], re.I | re.S):
        match = re.fullmatch(r"(\d+(?:-\d+(?:\.\d+)?){2})\s*\|\s*([^|]+?)\s*\(vacant lot\)", clean(item), re.I)
        if not match or match[1] in seen:
            continue
        pid, address = match.groups()
        seen.add(pid)
        rows.append({
            "id": "ny-newburgh-" + slug(pid), "source": "newburgh-landbank",
            "title": "%s, Newburgh (vacant lot)" % address,
            "state": "NY", "county": "Orange", "locality": "Newburgh", "apn": pid,
            "acres": None, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": NEWBURGH_URL, "address": address,
            "lat": None, "lon": None, "geometry": None,
            "facts": [fact("availability", "Currently available for sale", "="),
                      fact("parcel_number", pid, "=")],
            "tags": ["land bank vacant lot", "application required"],
        })
    return rows


def newburgh_landbank(fetch, now, warn):
    rows = parse_newburgh_sale(fetch.text(NEWBURGH_URL))
    return rows, {"complete": True, "upstream_total": len(rows)}


SLCO_SALE = "https://www.saltlakecounty.gov/real-estate/public-sale/"
SLCO_ASSESSOR = "https://apps.saltlakecounty.gov/slcogis/rest/services/Assessor/Parcel_Viewer_external/MapServer/5/query"


def parse_salt_lake_notices(page):
    if not re.search(r"<h2\b[^>]*>\s*Available Parcels\s*</h2>", page, re.I):
        raise StructureError("Salt Lake County's available parcels section changed")
    blocks = re.split(r'<div class="accordion-item rack" id="(s-\d+)"', page)[1:]
    for anchor, block in zip(blocks[::2], blocks[1::2]):
        button = re.search(r"<button\b[^>]*>(.*?)</button>", block, re.S)
        fields = {}
        for label, value in re.findall(r"<strong\b[^>]*>([^<]+)</strong>\s*:?\s*([^<]*)", block):
            fields[clean(label).rstrip(":")] = clean(value).lstrip(":").strip()
        pid = fields.get("Parcel #", "")
        if not re.fullmatch(r"\d{2}-\d{2}-\d{3}-\d{3}-\d{4}", pid) or not button:
            raise StructureError("Salt Lake County sale listing is missing a parcel number or address")
        close = datetime.datetime.strptime(fields.get("Offer Close Date", ""), "%B %d, %Y").date()
        yield anchor, pid, clean(button[1]), number(fields.get("Total Acreage")), number(fields.get("Minimum Price")), close


def parse_salt_lake_sales(notices, features):
    parcels = {(f.get("attributes") or {}).get("parcel_id"): f for f in features}
    rows = []
    for anchor, pid, address, acres, price, close in notices:
        feature = parcels.get(pid.replace("-", ""), {})
        attr = feature.get("attributes") or {}
        if attr.get("full_mkt_total_bldg") != 0 or attr.get("adjusted_total_bldg") != 0:
            continue
        if any(number(attr.get(key)) for key in ("total_sq_ft", "num_housing_units")):
            continue
        if not acres or not price:
            continue
        url = SLCO_SALE + "#" + anchor
        city = address.split(",")[1].strip() if len(address.split(",")) > 2 else ""
        row = {
            "id": "ut-slco-" + slug(pid), "source": "salt-lake-county-surplus",
            "title": "%s (Salt Lake County surplus land)" % address,
            "state": "UT", "county": "Salt Lake", "locality": city, "apn": pid,
            "acres": acres, "price": price, "price_kind": "min_bid", "offering": "auction",
            "status": "auction_terms", "deadline": None, "offer_close_date": close.isoformat(),
            "url": url, "address": address, "lat": None, "lon": None, "geometry": None,
            "facts": [
                fact("availability", "Available for public offers", url),
                fact("parcel_number", pid, url),
                fact("price", "$%s minimum offer" % "{:,.2f}".format(price), url,
                     "Appraisal, filing and administrative fees are separate."),
                fact("deadline", "%s (county local date)" % close.strftime("%B %d, %Y"), url),
            ],
            "tags": ["county surplus land", "sealed offer"],
        }
        if rings := (feature.get("geometry") or {}).get("rings"):
            parcel_url = one_parcel_url(SLCO_ASSESSOR, "parcel_id='%s'" % pid.replace("-", ""))
            apply_geometry(row, rings, parcel_url, "Salt Lake County Assessor")
        rows.append(row)
    return rows


def salt_lake_county_surplus(fetch, now, warn):
    notices = list(parse_salt_lake_notices(fetch.text(SLCO_SALE)))
    features = []
    if notices:
        ids = quote_list(pid.replace("-", "") for _, pid, *_ in notices)
        _, features = arcgis_query(fetch, SLCO_ASSESSOR, "parcel_id IN (%s)" % ids,
                                   "parcel_id,full_mkt_total_bldg,adjusted_total_bldg,total_sq_ft,num_housing_units")
    rows = parse_salt_lake_sales(notices, features)
    return rows, {"complete": True, "upstream_total": len(notices)}


MUNCIE_VACANT = "https://muncielandbank.org/vacant-lot-auction/"


def parse_muncie_lot(page, url, now):
    from zoneinfo import ZoneInfo

    if not re.search(r'"name":"Vacant Lot","@id":"https://muncielandbank\.org/product-category/vacant-lot/"', page):
        return None
    title = re.search(r"<title>([^<]+?)\s*-\s*Muncie Land Bank</title>", page)
    minimum = re.search(r"The minimum bid is \$([\d,]+(?:\.\d{2})?)\b", clean(page), re.I)
    deadline = re.search(r'<label\b[^>]*\bid="dateend"[^>]*>([^<]+)</label>\s*<label>E[SD]T</label>', page)
    if not title or not minimum or not deadline or 'id="yith-wcact-form-bid"' not in page:
        return None
    land_name = clean(title[1])
    price = number(minimum[1])
    cutoff = datetime.datetime.strptime(clean(deadline[1]), "%B %d, %Y %I:%M %p").replace(
        tzinfo=ZoneInfo("America/Indiana/Indianapolis")).astimezone(datetime.timezone.utc)
    if not land_name or not price or cutoff <= now:
        return None
    return {
        "id": "in-muncie-" + url.rstrip("/").rsplit("/", 1)[1], "source": "muncie-landbank",
        "title": "%s, Muncie (land bank auction)" % land_name, "state": "IN", "county": "Delaware",
        "locality": "Muncie", "apn": "", "acres": None, "price": price, "price_kind": "min_bid",
        "offering": "auction", "status": "auction_open", "deadline": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "url": url, "address": land_name, "lat": None, "lon": None, "geometry": None,
        "facts": [fact("availability", "Open Muncie Land Bank vacant-lot auction", "="),
                  fact("price", "$%s minimum bid" % "{:,.2f}".format(price), "=")],
        "tags": ["land bank vacant lot", "auction terms apply"],
    }


def muncie_landbank(fetch, now, warn):
    page = fetch.text(MUNCIE_VACANT)
    if "Vacant Lot Auction" not in page:
        raise StructureError("Muncie's vacant lot auction directory changed")
    urls = set(re.findall(r'href="(https://muncielandbank\.org/product/[a-z0-9-]+/)"', page))
    rows = [parse_muncie_lot(fetch.text(url), url, now) for url in sorted(urls)]
    return [r for r in rows if r], {"complete": True, "upstream_total": len(urls)}


HARRIS_SALE = "https://www.hctax.net/Property/listings/taxsalelisting"
HARRIS_ASSESSOR = "https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/0/query"


def parse_harris_notices(page):
    date = re.search(r"<h2\b[^>]*>\s*Sale Date:\s*([A-Za-z]+ \d{1,2}, \d{4})\s*</h2>", page)
    if not date or "list-listings-2" not in page:
        raise StructureError("Harris County's current sale directory changed")
    sales_date = datetime.datetime.strptime(date[1], "%B %d, %Y").date()
    notices = {}
    for card in re.split(r'<li class="row listing">', page)[1:]:
        summary = card.split('<div class="modal fade"', 1)[0]
        if not re.search(r'''class=["']For Sale-small["']''', summary):
            continue
        parcel = re.search(r"Account#:\s*<strong>\s*(\d{13})\s*</strong>", summary)
        price = re.search(r"Minimum Bid:\s*\$\s*<strong>\s*([\d,]+(?:\.\d{2})?)\s*</strong>", summary)
        if not parcel:
            raise StructureError("Harris County's current sale card has no HCAD account")
        notices[parcel[1]] = number(price[1]) if price else None
    return sales_date, notices


def parse_harris_sale(sales_date, notices, features):
    rows, seen = [], set()
    for feature in features:
        attr = feature.get("attributes") or {}
        pid = attr.get("acct_num")
        if pid not in notices or pid in seen or attr.get("state_class") not in ("C1", "C2"):
            continue
        if attr.get("bld_value") != 0 or attr.get("impr_value") != 0:
            continue
        seen.add(pid)
        price = notices[pid]
        city = clean(attr.get("site_city") or "").title()
        acres = number(attr.get("acreage_1")) or rings_acres((feature.get("geometry") or {}).get("rings") or [])
        row = {
            "id": "tx-harris-" + pid, "source": "harris-county-tax-sales",
            "title": "Harris County parcel %s (tax sale)" % pid, "state": "TX", "county": "Harris",
            "locality": city, "apn": pid, "acres": round(acres, 4) if acres else None,
            "price": price, "price_kind": "min_bid" if price else "none",
            "offering": "auction", "status": "auction_terms", "deadline": None,
            "offer_close_date": sales_date.isoformat(), "url": HARRIS_SALE, "address": "",
            "lat": None, "lon": None, "geometry": None,
            "facts": [fact("availability", "For sale in the county's current tax auction", "="),
                      fact("parcel_number", pid, "="),
                      fact("deadline", sales_date.strftime("%B %d, %Y"), "=")],
            "tags": ["county tax sale", "vacant lot", "auction terms apply"],
        }
        if price:
            row["facts"].append(fact("price", "$%s published minimum bid" % "{:,.2f}".format(price), "=",
                                     "Confirm the bid amount and terms with the county before the sale."))
        if rings := (feature.get("geometry") or {}).get("rings"):
            outline = one_parcel_url(HARRIS_ASSESSOR, "acct_num='%s'" % pid)
            apply_geometry(row, rings, outline, "Harris Central Appraisal District")
        rows.append(row)
    return rows


def harris_county_tax_sales(fetch, now, warn):
    from zoneinfo import ZoneInfo

    sales_date, notices = parse_harris_notices(fetch.text(HARRIS_SALE))
    if sales_date < now.astimezone(ZoneInfo("America/Chicago")).date():
        return [], {"complete": True, "upstream_total": 0}
    ids, parcels = sorted(notices), []
    for start in range(0, len(ids), 20):
        where = "acct_num IN (%s)" % quote_list(ids[start:start + 20])
        _, items = arcgis_query(fetch, HARRIS_ASSESSOR, where, "acct_num,site_city,state_class,acreage_1,bld_value,impr_value")
        parcels.extend(items)
    rows = parse_harris_sale(sales_date, notices, parcels)
    return rows, {"complete": True, "upstream_total": len(notices)}


GLYNN_SALE = "https://www.gblba.org/properties"


def parse_glynn_landbank(page):
    section = re.search(r"<h2\b[^>]*>\s*Available Properties\s*</h2>(.*?)</main>", page, re.I | re.S)
    if not section:
        raise StructureError("Glynn-Brunswick's available properties section changed")
    rows = []
    for heading, rest in re.findall(r"<h3\b[^>]*>(.*?)</h3>(.*?)(?=<h3|$)", section[1], re.I | re.S):
        details = re.match(r"\s*<h4\b[^>]*>(.*?)</h4>(.*?)</div>", rest, re.I | re.S)
        if not details:
            continue
        description = clean(details[2])
        acreage = re.search(r"\b([\d.]+)\s+acre\s+(?:wooded|commercial|cleared|vacant|residential)\s+lot\b", description, re.I)
        amount = re.fullmatch(r"\$([\d,]+(?:\.\d{2})?)", clean(details[1]))
        if not acreage or not amount or re.search(r"\b(?:foreclosure|demolition|structure|dwelling|sold|pending)\b", description, re.I):
            continue
        address = clean(heading)
        if not re.match(r"^\d+\s+[\w-]", address):
            continue
        rows.append({
            "id": "ga-glynn-" + slug(address), "source": "glynn-brunswick-landbank",
            "title": "%s, Brunswick (land bank lot)" % address,
            "state": "GA", "county": "Glynn", "locality": "Brunswick", "apn": "",
            "acres": number(acreage[1]), "price": number(amount[1]), "price_kind": "application",
            "offering": "sale", "status": "listed", "deadline": None,
            "url": GLYNN_SALE, "address": address, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("availability", "Available from the Glynn-Brunswick Land Bank Authority", "="),
                      fact("price", clean(details[1]) + " published price", "=", "The Land Bank reviews purchase applications.")],
            "tags": ["land bank vacant lot", "application required"],
        })
    return rows


def glynn_brunswick_landbank(fetch, now, warn):
    rows = parse_glynn_landbank(fetch.text(GLYNN_SALE))
    return rows, {"complete": True, "upstream_total": len(rows)}


KING_SURPLUS = "https://kingcounty.gov/en/dept/executive-services/buildings-property/facilities-management/real-estate-services/sales"
KING_ASSESSOR = "https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx"


def parse_king_surplus(page):
    section = re.search(r"<h2\b[^>]*>\s*Surplus Property\s*</h2>(.*?)</div>", page, re.I | re.S)
    if not section:
        raise StructureError("King County's surplus sales section changed")
    paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", section[1], re.I | re.S)
    rows = []
    for i, paragraph in enumerate(paragraphs[:-4]):
        if clean(paragraph) != "Vacant Land":
            continue
        pid = re.fullmatch(r"Parcel Number (\d{6}-\d{4})", clean(paragraphs[i + 1]))
        price = re.fullmatch(r"\$([\d,]+(?:\.\d{2})?)", clean(paragraphs[i + 4]))
        address = clean(paragraphs[i + 2])
        if not pid or not price or not address:
            continue
        rows.append((pid[1], address, number(price[1])))
    return rows


def king_county_surplus(fetch, now, warn):
    rows = []
    for pid, address, price in parse_king_surplus(fetch.text(KING_SURPLUS)):
        assessor = KING_ASSESSOR + "?ParcelNbr=" + pid.replace("-", "")
        acreage = re.search(r"\bAcres\s+([\d.]+)\b", clean(fetch.text(assessor)))
        rows.append({
            "id": "wa-king-surplus-" + slug(pid), "source": "king-county-current-surplus",
            "title": "King County parcel %s (vacant surplus land)" % pid,
            "state": "WA", "county": "King", "locality": "", "apn": pid,
            "acres": number(acreage[1]) if acreage else None, "price": price, "price_kind": "cash",
            "offering": "sale", "status": "listed", "deadline": None, "url": KING_SURPLUS, "address": address,
            "lat": None, "lon": None, "geometry": None,
            "facts": [fact("availability", "Vacant land offered for sale by King County", "="),
                      fact("price", "$%s asking price" % "{:,.2f}".format(price), "="),
                      fact("parcel_number", pid, assessor)],
            "tags": ["county surplus land", "vacant lot"],
        })
    return rows, {"complete": True, "upstream_total": len(rows)}


CALTRANS_LAND = "https://dot.ca.gov/programs/right-of-way/excess-lands-properties-for-sale"


def parse_caltrans_brochure(brochure, url, now):
    from zoneinfo import ZoneInfo

    text = " ".join(brochure.split())
    identifying_parcel = re.search(r"\bDATA SHEET\s+DD\s+(\d{4,6}-\d{2}-\d{2})\b", text)
    if not identifying_parcel:
        return None
    data_sheet = text[identifying_parcel.end():]
    price = re.search(r"\bMINIMUM BID\s+\$([\d,]+(?:\.\d{2})?)\b", data_sheet)
    location = re.search(r"\bLOCATION\s+([^$]{1,160}?)\s*-\s*Google Maps\s+SIZE\b", data_sheet)
    area = re.search(r"\bTotal\s+([\d,]+(?:\.\d+)?)\s*(?:\+/-\s*)?sf\.", data_sheet, re.I)
    county = re.search(r"\bPROPERTY\s+Unimproved vacant lot\..{0,400}?\bin ([A-Za-z][A-Za-z .'-]+) County\.", data_sheet)
    cutoff = re.search(r"Submittal Deadline\s*[–-]\s*\w+,\s+([A-Za-z]+ \d+, \d{4}),\s+by\s+(\d{1,2}:\d{2} [AP]M)\s+\(Pacific", text)
    if not all((price, location, county, cutoff)):
        return None
    deadline = datetime.datetime.strptime(" ".join(cutoff.groups()), "%B %d, %Y %I:%M %p").replace(
        tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(datetime.timezone.utc)
    if deadline <= now:
        return None
    pid, address, county_name = identifying_parcel[1], location[1], county[1]
    sqft = number(area[1]) if area else None
    bid = number(price[1])
    return {
        "id": "ca-caltrans-" + slug(pid), "source": "caltrans-surplus",
        "title": "%s, %s County (Caltrans sealed bid)" % (address, county_name),
        "state": "CA", "county": county_name, "locality": "", "apn": "", "address": address,
        "acres": round(sqft / 43560, 4) if sqft else None, "price": bid, "price_kind": "min_bid",
        "offering": "auction", "status": "auction_open", "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "url": url, "lat": None, "lon": None, "geometry": None,
        "facts": [fact("availability", "Unimproved vacant lot offered by sealed bid", "="),
                  fact("parcel_number", "Caltrans file DD " + pid, "=")],
        "tags": ["state surplus land", "sealed bid"],
    }


def caltrans_surplus(fetch, now, warn):
    page = fetch.text(CALTRANS_LAND)
    if "Auction Brochure/Information" not in page:
        raise StructureError("Caltrans excess lands sale table changed")
    rows = []
    for raw in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, re.I | re.S):
        if not re.search(r"\b(?:unimproved vacant land|vacant lot)\b", clean(raw), re.I):
            continue
        link = re.search(r'<a\b[^>]+\bhref="([^"]+\.pdf)"', raw, re.I)
        if not link:
            continue
        url = urllib.parse.urljoin(CALTRANS_LAND, html.unescape(link[1]))
        if urllib.parse.urlsplit(url).hostname != "dot.ca.gov":
            continue
        row = parse_caltrans_brochure(pdf_text(fetch, url, extraction_mode="plain"), url, now)
        if row:
            rows.append(row)
    return rows, {"complete": True, "upstream_total": len(rows)}


MA_LAND_FOR_HOMES = "https://www.mass.gov/info-details/state-land-for-homes"
MA_AUCTION_COUNTIES = {"Billerica": "Middlesex", "Milford": "Worcester", "Rowley": "Essex"}


def parse_ma_land_for_homes(page, now):
    from zoneinfo import ZoneInfo

    section = re.search(r'<h3\b[^>]*\bid="upcoming-auction"[^>]*>(.*?)</div>', page, re.I | re.S)
    if not section:
        if "Development Opportunities" in page:
            return []
        raise StructureError("Massachusetts State Land for Homes auction section changed")
    when = re.search(r"\bavailable at auction on (?:\w+,\s*)?"
                     r"([A-Za-z]+ \d{1,2}, \d{4}) at (\d{1,2}(?::\d{2})?\s*[ap]m)\b", clean(section[1]), re.I)
    if not when:
        raise StructureError("Massachusetts public land auction time changed")
    zone = ZoneInfo("America/New_York")
    start_time = when[2].replace(" ", "")
    time_pattern = "%I:%M%p" if ":" in start_time else "%I%p"
    start = datetime.datetime.strptime(when[1] + " " + start_time, "%B %d, %Y " + time_pattern).replace(tzinfo=zone)
    if start.date() < now.astimezone(zone).date():
        return []
    lots = re.split(r'<a\b[^>]*href="(/doc/state-land-for-homes-flyer-[a-z0-9-]+/download)"[^>]*>(.*?)</a>',
                    section[1], flags=re.I | re.S)[1:]
    rows = []
    for link, label, description in zip(lots[::3], lots[1::3], lots[2::3]):
        description = clean(description)
        if not re.search(r"\b(?:vacant|undeveloped)\b", description, re.I):
            continue
        acres = re.search(r"\b([\d.]+)\s*-?\s*acres?\b", description, re.I)
        address = clean(label)
        if not acres or ", " not in address:
            continue
        city = address.rsplit(", ", 1)[1]
        url = MA_LAND_FOR_HOMES + "#upcoming-auction"
        rows.append({
            "id": "ma-dcamm-" + slug(address), "source": "massachusetts-land-for-homes",
            "title": "%s (Massachusetts surplus land auction)" % address,
            "state": "MA", "county": MA_AUCTION_COUNTIES.get(city, ""), "locality": city, "apn": "",
            "address": address, "acres": number(acres[1]), "price": None, "price_kind": "none",
            "offering": "auction", "status": "auction_terms", "deadline": None,
            "offer_close_date": start.date().isoformat(), "url": url, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("availability", "Available at the Commonwealth's public land auction", "="),
                      fact("sale_program", "State Land for Homes", urllib.parse.urljoin(MA_LAND_FOR_HOMES, link)),
                      fact("auction_start", start.strftime("%B %d, %Y at %I:%M %p %Z"), "=")],
            "tags": ["state surplus land", "housing development"],
        })
    return rows


def massachusetts_land_for_homes(fetch, now, warn):
    rows = parse_ma_land_for_homes(fetch.text(MA_LAND_FOR_HOMES), now)
    return rows, {"complete": True, "upstream_total": len(rows)}


LAKOTA_ND_LOTS = "https://www.lakota-nd.com/?SEC=12104B06-4E76-49CC-934C-4ACF2D87FF55"
LAKOTA_HULSTRAND_PLAT = "4497819287fc44b19312041ba46db37ef18f56e461973a119e41b120ee3824e3"
# Square footage transcribed from the city's published plat. Verify the file before using it.
LAKOTA_HULSTRAND_SQFT = {"1": 36337, "2": 34733, "3": 34733, "4": 34733}


def parse_lakota_lots(page):
    text = clean(page)
    rate = re.search(r"All residential city lots are sold for \$([\d.]+)/SF\b", text, re.I)
    section = re.search(r"<h2>Hulstrand Addition</h2>(.*?)</aside>", page, re.I | re.S)
    if not rate or not section or not number(rate[1]):
        raise StructureError("Lakota residential lot program format changed")
    lots = re.search(r"\bLots? ([\d\s,&]+?) (?:is|are) for sale\.", clean(section[1]), re.I)
    plat = re.search(r'<img\b[^>]*src="([^\"]+)"[^>]*alt="Hulstrand Addition"', section[1], re.I)
    if not lots or not plat:
        raise StructureError("Lakota lot availability or plat is missing")
    numbers = re.findall(r"\d+", lots[1])
    if any(lot not in LAKOTA_HULSTRAND_SQFT for lot in numbers):
        raise StructureError("Lakota lists a lot absent from the verified plat")
    return number(rate[1]), numbers, urllib.parse.urljoin(LAKOTA_ND_LOTS, html.unescape(plat[1]))


def lakota_nd_lots(fetch, now, warn):
    rate, lots, plat = parse_lakota_lots(fetch.text(LAKOTA_ND_LOTS))
    if hashlib.sha256(fetch.bytes(plat)).hexdigest() != LAKOTA_HULSTRAND_PLAT:
        raise StructureError("Lakota subdivision plat changed and the lot sizes need review")
    rows = []
    for lot in lots:
        sqft = LAKOTA_HULSTRAND_SQFT[lot]
        rows.append({
            "id": "nd-lakota-hulstrand-" + lot, "source": "lakota-nd-lots",
            "title": "Hulstrand Addition lot %s, Lakota" % lot,
            "state": "ND", "county": "Nelson", "locality": "Lakota", "apn": "", "address": "",
            "acres": round(sqft / 43560, 4), "price": round(sqft * rate, 2), "price_kind": "application",
            "offering": "sale", "status": "listed", "deadline": None,
            "url": LAKOTA_ND_LOTS, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("parcel_number", "Hulstrand Addition Lot " + lot, plat),
                      fact("acreage", "{:,} square feet on the city plat".format(sqft), plat),
                      fact("price", "City price of $%.2f per square foot" % rate, "="),
                      fact("sale_program", "Construction must start within 18 months of sale", "=")],
            "tags": ["city residential lot", "construction required"],
        })
    return rows, {"complete": True, "upstream_total": len(rows)}


PRINCETON_MN_SALE = "https://princetonmn.org/city-owned-properties"


def parse_princeton_industrial(brochure):
    rate = re.search(r"\bSale Price Per Lot:\s*\$([\d,.]+) per acre", brochure, re.I)
    parcels = re.findall(r"\bPID \d+:\s*(\d{2}-\d{3}-\d{4})\s+([\d.]+) acres\b", brochure, re.I)
    if not rate or not parcels or "lots available for industrial development" not in brochure.lower():
        raise StructureError("Princeton Business Park brochure format changed")
    return [(pid, number(acres), round(number(acres) * number(rate[1]), 2)) for pid, acres in parcels]


def princeton_mn_lots(fetch, now, warn):
    page = fetch.text(PRINCETON_MN_SALE)
    text = clean(page)
    if "City Owned Properties For Sale" not in text:
        raise StructureError("Princeton city lot listings format changed")
    rows = []
    brochure = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>\s*Two Lots Sale of Land Brochure\s*</a>', page, re.I)
    if brochure and "two City owned lots currently for sale" in text:
        url = urllib.parse.urljoin(PRINCETON_MN_SALE, html.unescape(brochure[1]).strip())
        for pid, acres, price in parse_princeton_industrial(pdf_text(fetch, url, extraction_mode="plain")):
            rows.append((pid, acres, price, "application", "Princeton Business Park", url))
    commercial = re.search(r"Commercial Lot for Sale.{0,900}?Sale Price per Lot: Lot Size: \$([\d,.]+) "
                           r"PID: (\d{2}-\d{3}-\d{4}) .{0,80}? or ([\d.]+) acres", text, re.I)
    if commercial:
        rows.append((commercial[2], number(commercial[3]), number(commercial[1]), "cash", "7th Avenue North", PRINCETON_MN_SALE))
    result = []
    for pid, acres, price, kind, location, proof in rows:
        result.append({
            "id": "mn-princeton-" + slug(pid), "source": "princeton-mn-lots",
            "title": "%s parcel %s, Princeton" % (location, pid),
            "state": "MN", "county": "Mille Lacs", "locality": "Princeton", "apn": pid, "address": "",
            "acres": acres, "price": price, "price_kind": kind, "offering": "sale", "status": "listed",
            "deadline": None, "url": PRINCETON_MN_SALE, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("parcel_number", pid, proof), fact("acreage", "%g acres" % acres, proof),
                      fact("sale_program", "Industrial development required" if kind == "application" else
                           "Commercial lot for sale by the City", "=")],
            "tags": ["city development land", "industrial site" if kind == "application" else "commercial site"],
        })
    return result, {"complete": True, "upstream_total": len(result)}


BURLINGTON_IA_SALE = "https://www.burlingtoniowa.org/2545/City-Owned-Properties-For-Sale"


def parse_burlington_lots(page):
    sections = re.findall(r"<h2\b[^>]*>(.*?)</h2>(.*?)(?=<h2\b|</main>)", page, re.I | re.S)
    rows = {}
    found = False
    for heading, section in sections:
        title = clean(heading)
        if not title.startswith("City-Owned Lots - For Sale"):
            continue
        found = True
        listing = re.search(r"<ul\b[^>]*>(.*?)</ul>", section, re.I | re.S)
        if not listing:
            continue
        for item in re.findall(r"<li\b[^>]*>(.*?)</li>", listing[1], re.I | re.S):
            location = clean(item)
            if re.search(r"\b(?:sold|pending|withdrawn|under contract)\b", location, re.I):
                continue
            source = re.search(r'\bhref="(https://www\.dmcgis\.com/[^\"]+\bparcelid=(\d{2}-\d{2}-\d{3}-\d{3}))"', item, re.I)
            inline_id = re.fullmatch(r"Parcel:\s*(\d{2}-\d{2}-\d{3}-\d{3})", location, re.I)
            if not source and not inline_id:
                continue
            pid = source[2] if source else inline_id[1]
            url = html.unescape(source[1]) if source else BURLINGTON_IA_SALE
            rows[pid] = {
                "id": "ia-burlington-" + pid, "source": "burlington-ia-lots",
                "title": ("Burlington parcel " + pid if inline_id else "%s, Burlington" % location) + " (city land sale)",
                "state": "IA", "county": "Des Moines", "locality": "Burlington", "apn": pid,
                "address": "" if inline_id else location, "acres": None, "price": None, "price_kind": "none",
                "offering": "auction", "status": "auction_terms", "deadline": None,
                "url": BURLINGTON_IA_SALE, "lat": None, "lon": None, "geometry": None,
                "facts": [fact("parcel_number", pid, url), fact("availability", "City accepts bids at council meetings", "=")],
                "tags": ["city-owned vacant lot", "construction required" if "Structure Required" in title else "check buildability"],
            }
    if not found:
        raise StructureError("Burlington city sale lot sections changed")
    return list(rows.values())


def burlington_ia_lots(fetch, now, warn):
    rows = parse_burlington_lots(fetch.text(BURLINGTON_IA_SALE))
    return rows, {"complete": True, "upstream_total": len(rows)}


DESOTO_FL_SALE = "https://www.desotoclerk.com/clerk-services/tax-deeds/"
FL_PARCEL_GIS = "https://services9.arcgis.com/Gh9awoU677aKree0/ArcGIS/rest/services/Florida_Statewide_Cadastral/FeatureServer/0/query"
FL_VACANT_USE = {"000": "Vacant residential", "010": "Vacant commercial", "040": "Vacant industrial"}


def parse_desoto_auctions(page, now):
    from zoneinfo import ZoneInfo

    catalog = re.search(r'<tax-deed-sales\b[^>]*:taxdeeds="([^\"]+)"', page, re.I)
    timing = re.search(r"\bAll sales start at (\d{1,2}:\d{2} [AP]M)\b", clean(page), re.I)
    if not catalog or not timing:
        raise StructureError("DeSoto County scheduled tax deed catalog or auction time changed")
    local_time = datetime.datetime.strptime(timing[1], "%I:%M %p").time()
    zone = ZoneInfo("America/New_York")
    rows = {}
    for item in json.loads(html.unescape(catalog[1])):
        if item.get("status") != "scheduled":
            continue
        apn = item.get("parcel") or ""
        if not re.fullmatch(r"\d{2}-\d{2}-\d{2}-[A-Z0-9]{4}-[A-Z0-9]{4}-\d{4}", apn):
            continue
        date = datetime.date.fromisoformat(item["iso_sale_date"])
        start = datetime.datetime.combine(date, local_time, zone)
        price = number(item.get("opening_bid"))
        if start > now and price:
            rows[apn.replace("-", "")] = (apn, price, start)
    return rows


def desoto_fl_auctions(fetch, now, warn):
    sale = parse_desoto_auctions(fetch.text(DESOTO_FL_SALE), now)
    rows = []
    if sale:
        match = "CO_NO=24 AND PARCELNO IN (%s)" % quote_list(sorted(sale))
        _, features = arcgis_query(fetch, FL_PARCEL_GIS, match, "PARCELNO,DOR_UC,NO_BULDNG,LND_SQFOOT")
        seen = set()
        for feature in features:
            a = feature["attributes"]
            parcel = a.get("PARCELNO")
            use = FL_VACANT_USE.get(a.get("DOR_UC"))
            if parcel not in sale or parcel in seen or not use or a.get("NO_BULDNG") != 0:
                continue
            seen.add(parcel)
            apn, price, start = sale[parcel]
            rings = (feature.get("geometry") or {}).get("rings") or []
            sqft = number(a.get("LND_SQFOOT"))
            acres = round(sqft / 43560, 4) if sqft else None
            gis = one_parcel_url(FL_PARCEL_GIS, "CO_NO=24 AND PARCELNO='%s'" % parcel)
            row = {
                "id": "fl-desoto-" + apn.lower(), "source": "desoto-fl-auctions",
                "title": "DeSoto County parcel %s (Florida tax deed sale)" % apn,
                "state": "FL", "county": "DeSoto", "locality": "", "apn": apn, "address": "",
                "acres": acres, "price": price, "price_kind": "min_bid", "offering": "auction",
                "status": "auction_terms", "deadline": start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "url": DESOTO_FL_SALE, "lat": None, "lon": None, "geometry": None,
                "facts": [fact("parcel_number", apn, "="), fact("use_code", use + " with no assessed buildings", gis),
                          fact("auction_start", start.strftime("%B %d, %Y at %I:%M %p %Z"), "=")],
                "tags": ["county tax deed auction", "in-person bidding"],
            }
            if rings:
                apply_geometry(row, rings, gis, "Florida Department of Revenue parcel map")
            rows.append(row)
    return rows, {"complete": True, "upstream_total": len(sale)}


GREENBURGH_NY_NOTICE = "https://www.greenburghny.com/m/newsflash/Home/Detail/3871"


def parse_greenburgh_catalog(page, catalog_url, now):
    from zoneinfo import ZoneInfo

    if "Town of Greenburgh Online Only Tax Foreclosure Real Estate Auction" not in page:
        raise StructureError("Greenburgh auction catalog identity changed")
    cards = re.split(r"lots\.lotsById\[(\d+)\] = lot\d+;", page)[1:]
    rows = []
    for item, card in zip(cards[::2], cards[1::2]):
        detail = clean(card)
        if not re.search(r"\bResidential vacant land\. (?:Combined lot\. )?Tax Map #:", detail, re.I):
            continue
        time = re.search(r"\bCloses\s*:\s*([A-Za-z]{3} \d{1,2}, \d{4} \d{1,2}:\d{2}:\d{2} [AP]M)\s+E[SD]T\b", detail)
        price = re.search(r"\bStarting Bid:\s*\$([\d,.]+)", detail, re.I)
        parcels = re.search(r"Tax Map #:\s*([\d. -]+)\s+Lot Size:\s*([\d.]+)\s*(?:\+/-\s*)?Acres", detail, re.I)
        link = re.search(r'<a\b[^>]*href="([^\"]+\bitemId=' + item + r')"[^>]*>\s*More Info / Bid', card, re.I)
        if not (time and price and parcels and link):
            continue
        start = datetime.datetime.strptime(time[1], "%b %d, %Y %I:%M:%S %p").replace(tzinfo=ZoneInfo("America/New_York"))
        if start <= now:
            continue
        ids = parcels[1].split()
        url = urllib.parse.urljoin(catalog_url, html.unescape(link[1]))
        rows.append({
            "id": "ny-greenburgh-auction-" + item, "source": "greenburgh-ny-auctions",
            "title": "Greenburgh %s %s (town tax foreclosure auction)" % ("parcel" if len(ids) == 1 else "parcels", " and ".join(ids)),
            "state": "NY", "county": "Westchester", "locality": "Greenburgh", "apn": ids[0] if len(ids) == 1 else "",
            "address": "", "acres": number(parcels[2]), "price": number(price[1]), "price_kind": "min_bid",
            "offering": "auction", "status": "auction_terms", "deadline": start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "url": url, "lat": None, "lon": None, "geometry": None,
            "facts": [fact("parcel_number", " · ".join(ids), "="),
                      fact("sale_program", "Two parcels offered as one lot" if len(ids) == 2 else "Town tax foreclosure sale", GREENBURGH_NY_NOTICE)],
            "tags": ["town tax foreclosure", "online bidding"],
        })
    return rows


def greenburgh_ny_auctions(fetch, now, warn):
    notice = fetch.text(GREENBURGH_NY_NOTICE)
    link = re.search(r'href="(https://aarauctions\.com/servlet/Search\.do\?auctionId=\d+)"', notice, re.I)
    if not link:
        raise StructureError("Greenburgh town notice no longer links to an auction catalog")
    rows = parse_greenburgh_catalog(fetch.text(link[1]), link[1], now)
    return rows, {"complete": True, "upstream_total": len(rows)}


ROCHESTER_NY_SALE = "https://www.cityofrochester.gov/departments/finance-department/tax-foreclosure-auctions-environmental-auctions"


def parse_rochester_environmental_pdf(report, sale_date, url):
    if "Estimated Minimum Bid" not in report or "Demolition Status" not in report:
        raise StructureError("Rochester environmental auction property list changed")
    rows = []
    for line in report.splitlines():
        match = re.fullmatch(r"(\d{3}\.\d{2}-\d+-\d+(?:\.\d+)?)\s+(.+?)\s+(\d{5})\s+"
                             r"([\d.]+\s*X\s*[\d.]+)\s+(?:Residential,|Commercial,) Vacant Land\s+"
                             r"\$[\d,.]+\s+\$([\d,.]+)\s*", line.strip(), re.I)
        if not match:
            continue
        pid, address, zipcode, dimensions, estimated_bid = match.groups()
        address = re.sub(r"^0+(?=\d)", "", address).title()
        rows.append({
            "id": "ny-rochester-land-" + slug(pid), "source": "rochester-ny-environmental",
            "title": "%s, Rochester (environmental auction lot)" % address,
            "state": "NY", "county": "Monroe", "locality": "Rochester", "apn": pid, "address": address,
            "acres": None, "price": None, "price_kind": "none", "offering": "auction", "status": "auction_terms",
            "deadline": None, "offer_close_date": sale_date.isoformat(), "url": ROCHESTER_NY_SALE,
            "lat": None, "lon": None, "geometry": None,
            "facts": [fact("parcel_number", pid, url), fact("lot_dimensions", dimensions + " feet", url),
                      fact("auction_start", sale_date.strftime("%B %d, %Y") + " at 10:00 a.m. Eastern", "="),
                      fact("minimum_bid", "City estimate $%s. Confirm before bidding." % estimated_bid, url),
                      fact("sale_program", "The city reports known or suspected contamination or other environmental hazards.", "=")],
            "tags": ["environmental auction", "known or suspected contamination"],
        })
    return rows


def rochester_ny_environmental(fetch, now, warn):
    from zoneinfo import ZoneInfo

    source = fetch.text(ROCHESTER_NY_SALE)
    text = clean(source)
    date = re.search(r"environmental sale will be held on \w+,\s*([A-Za-z]+ \d{1,2})(?:st|nd|rd|th)?,? (20\d{2})", text, re.I)
    if not date:
        return [], {"complete": True, "upstream_total": 0}
    auction = datetime.datetime.strptime(date[1] + " " + date[2], "%B %d %Y").date()
    if auction < now.astimezone(ZoneInfo("America/New_York")).date():
        return [], {"complete": True, "upstream_total": 0}
    report = re.search(r'<a\b[^>]*href="(/sites/default/files/[^\"]+\.pdf)"[^>]*>\s*City of Roc Auction List\b', source, re.I)
    if not report or not re.search(r"Auctions will begin at 10\s*AM\b", text, re.I):
        raise StructureError("Rochester auction lot sheet or start time changed")
    url = urllib.parse.urljoin(ROCHESTER_NY_SALE, report[1])
    rows = parse_rochester_environmental_pdf(pdf_text(fetch, url, extraction_mode="plain"), auction, url)
    return rows, {"complete": True, "upstream_total": len(rows)}


SOURCES = [
    {"id": "st-louis-lra", "name": "City of St. Louis vacant-lot inventory", "agency": "St. Louis Development Corporation / Land Reutilization Authority",
     "url": "https://www.stlouis-mo.gov/government/departments/sldc/real-estate/lra-owned-property-search.cfm", "state": "MO", "run": st_louis,
     "about": "City-owned vacant lots marked available in the city's open-data exports. Eligible Side Lot Program properties have an official application price."},
    {"id": "kansas-city-landbank", "name": "Land Bank of Kansas City vacant-lot inventory", "agency": "Land Bank of Kansas City, Missouri",
     "url": KC_PORTAL, "state": "MO", "run": kansas_city_landbank,
     "about": "Acquired vacant lots published via Kansas City Open Data, including zoning codes, lot area, and neighborhood context."},
    {"id": "arkansas-cosl", "name": "Arkansas Commissioner of State Lands", "agency": "Arkansas Commissioner of State Lands",
     "url": "https://auction.cosl.org/Auctions/ListingsView", "state": "AR", "run": arkansas,
     "about": "Tax-forfeited parcels offered after the county tax-sale auctions. Prices are minimum bids; terms and redemption rules apply."},
    {"id": "pittsburgh-vacant", "name": "City of Pittsburgh available vacant land", "agency": "City of Pittsburgh / Pittsburgh Land Bank",
     "url": PGH_URL, "state": "PA", "run": pittsburgh_vacant,
     "about": "Vacant city-owned parcels marked Available for Sale (Public Sale) in Pittsburgh's daily open-data inventory, with zoning, square footage, and coordinates."},
    {"id": "lucas-county-oh", "name": "Lucas County Land Bank vacant land (Toledo)", "agency": "Lucas County Land Bank",
     "url": LUCAS_URL, "state": "OH", "run": lucas_county_oh,
     "about": "Vacant land bank parcels in Toledo & Lucas County with GIS polygon boundaries, zoning codes, acreage, and legal descriptions."},
    {"id": "detroit-dlba", "name": "Detroit Land Bank Authority marketed vacant lots", "agency": "Detroit Land Bank Authority",
     "url": DLBA_URL, "state": "MI", "run": detroit_dlba,
     "about": "Actively marketed vacant lots from the official Detroit Land Bank GIS, including eligible Neighborhood Lots with the published program price."},
    {"id": "chicago-dpd", "name": "City of Chicago City-Owned Land Inventory (ChiBlockBuilder)", "agency": "City of Chicago Dept. of Planning & Development",
     "url": CHI_URL, "state": "IL", "run": chicago_dpd,
     "about": "Actively offered and open-application Chicago city-owned vacant lots with zoning classifications, lot square footage, and Q4/2027 application deadlines."},
    {"id": "louisville-landbank", "name": "Louisville Metro Landbank Authority available lots", "agency": "Louisville Metro Landbank Authority",
     "url": LOU_URL, "state": "KY", "run": louisville_landbank,
     "about": "Available vacant landbank lots with official buildability flags. Eligible My New Side Yard lots carry the published conditional price."},
    {"id": "la-county-ttc", "name": "Los Angeles County Tax-Defaulted Land Auctions", "agency": "Los Angeles County Treasurer & Tax Collector",
     "url": LA_TTC_URL, "state": "CA", "run": la_county_ttc, "historical_only": True,
     "about": "The original 2026 A and B auction events closed. The County publishes a separate catalog for the follow-up auction."},
    {"id": "broward-surplus", "name": "Broward County Surplus Real Property", "agency": "Broward County Board of County Commissioners",
     "url": "https://www.broward.org/realproperty", "state": "FL", "run": broward_surplus, "historical_only": True,
     "about": "The County surplus inventory includes multiple land uses and has no current sale status. Contact the Real Property Section for availability."},
    {"id": "orange-county-fl", "name": "Orange County Active Tax Deed Sales", "agency": "Orange County Comptroller / Tax Deed Sales",
     "url": ORANGE_FL_URL, "state": "FL", "run": orange_county_fl,
     "about": "Active scheduled tax deed auction parcels in Orange County, Florida with posted upcoming auction dates and coordinates."},
    {"id": "albany-landbank", "name": "Albany County Land Bank vacant land", "agency": "Albany County Land Bank Corporation",
     "url": ALBANY_URL, "state": "NY", "run": albany_landbank, "historical_only": True,
     "about": "Albany County's sale list governs current availability. The legacy GIS inventory contains held parcels outside that list."},
    {"id": "big-spring-tx", "name": "City of Big Spring city-owned vacant lots", "agency": "City of Big Spring, Texas",
     "url": BIGSPRING_URL, "state": "TX", "run": big_spring_tx, "historical_only": True,
     "about": "This city ownership map needs a match to a current sale or proposal notice."},
    {"id": "las-cruces-nm", "name": "City of Las Cruces city-owned vacant land", "agency": "City of Las Cruces, New Mexico",
     "url": LASCRUCES_URL, "state": "NM", "run": las_cruces_nm, "historical_only": True,
     "about": "This city ownership map needs a match to a current sale or proposal notice."},
    {"id": "baltimore-vacant", "name": "Baltimore City-Owned Vacant Properties (DMA)", "agency": "Baltimore City Dept. of Housing & Community Development",
     "url": BALTIMORE_URL, "state": "MD", "run": baltimore_vacant, "historical_only": True,
     "about": "This city ownership map needs a match to Baltimore's current public sale portal."},
    {"id": "king-county-wa", "name": "King County Tax-Title Vacant Land", "agency": "King County Real Estate Services",
     "url": KING_WA_URL, "state": "WA", "run": king_county_wa, "historical_only": True,
     "about": "The tax-title holdings layer needs a match to the county's current auction or direct-sale notices."},
    {"id": "charlotte-nc", "name": "City of Charlotte Undeveloped City-Owned Land", "agency": "City of Charlotte, North Carolina",
     "url": CHARLOTTE_URL, "state": "NC", "run": charlotte_nc, "historical_only": True,
     "about": "This city ownership map needs a match to a current sale or proposal notice."},
    {"id": "canton-ga", "name": "City of Canton City-Owned Land", "agency": "City of Canton, Georgia",
     "url": CANTON_GA_URL, "state": "GA", "run": canton_ga, "historical_only": True,
     "about": "This city ownership map needs a match to a current sale or proposal notice."},
    {"id": "san-miguel-co", "name": "San Miguel County Public Land Inventory", "agency": "San Miguel County, Colorado",
     "url": SANMIGUEL_CO_URL, "state": "CO", "run": san_miguel_co, "historical_only": True,
     "about": "This county ownership map needs a match to a current sale or proposal notice."},
    {"id": "navajo-county-az", "name": "Navajo County Back-Tax Auction Properties", "agency": "Navajo County, Arizona",
     "url": NAVAJO_AZ_URL, "state": "AZ", "run": navajo_county_az, "historical_only": True,
     "about": "The prior auction layer points to an earlier catalog. The County publishes a separate notice for the next sale."},
    {"id": "baton-rouge-la", "name": "East Baton Rouge Adjudicated Tax-Sale Land", "agency": "City-Parish of East Baton Rouge, Louisiana",
     "url": "https://www.brla.gov/455/adjudicated-property", "state": "LA", "run": baton_rouge_la, "historical_only": True,
     "about": "The assessor’s roll records adjudication. The Parish posts separate notices identifying properties that can be bid on at the next sale."},
    {"id": "cherry-hill-nj", "name": "Cherry Hill Township Vacant Lots", "agency": "Cherry Hill Township, New Jersey",
     "url": CHERRYHILL_NJ_URL, "state": "NJ", "run": cherry_hill_nj, "historical_only": True,
     "about": "This township ownership map needs a match to a current sale notice."},
    {"id": "orlando-vacant-fl", "name": "City of Orlando Vacant Lots Inventory", "agency": "City of Orlando, Florida",
     "url": ORLANDO_FL_URL, "state": "FL", "run": orlando_vacant_fl, "historical_only": True,
     "about": "The city's vacant-lot inventory needs a match to a current sale notice."},
    {"id": "delaware-in", "name": "Delaware County / Muncie Tax Sale Vacant Land", "agency": "Delaware County, Indiana",
     "url": DELAWARE_IN_URL, "state": "IN", "run": delaware_in, "historical_only": True,
     "about": "The October 2026 sale of tax certificates has ended."},
    {"id": "mille-lacs-mn", "name": "Mille Lacs County Tax-Forfeited Saleable Land", "agency": "Mille Lacs County, Minnesota",
     "url": MILLELACS_MN_URL, "state": "MN", "run": mille_lacs_mn,
     "about": "Saleable vacant tax-forfeited parcels in Mille Lacs County with GIS outlines, zoning, and waterfront indicators."},
    {"id": "otter-tail-mn", "name": "Otter Tail County Tax-Forfeited Land", "agency": "Otter Tail County, Minnesota",
     "url": OTTERTAIL_MN_URL, "state": "MN", "run": otter_tail_mn,
     "about": "Tax-forfeited land parcels in Otter Tail County, Minnesota with GIS boundaries and acreage."},
    {"id": "richmond-va", "name": "City of Richmond Surplus Vacant Properties", "agency": "City of Richmond, Virginia",
     "url": RICHMOND_VA_URL, "state": "VA", "run": richmond_va,
     "about": "City-owned vacant surplus properties in Richmond, Virginia with GIS outlines and lot area."},
    {"id": "montgomery-al", "name": "City of Montgomery General Surplus Property", "agency": "City of Montgomery, Alabama",
     "url": MONTGOMERY_AL_URL, "state": "AL", "run": montgomery_al,
     "about": "Public surplus city-owned properties in Montgomery, Alabama with coordinates and acreage."},
    {"id": "waterloo-ia", "name": "City of Waterloo Properties For Sale", "agency": "City of Waterloo, Iowa",
     "url": WATERLOO_IA_URL, "state": "IA", "run": waterloo_ia,
     "about": "Development and industrial park land for sale in Waterloo, Iowa with GIS outlines, zoning, and TIF districts."},
    {"id": "wyandotte-ks", "name": "Wyandotte County / KCK Land Bank Vacant Land", "agency": "Unified Government of Wyandotte County / KCK",
     "url": WYANDOTTE_KS_URL, "state": "KS", "run": wyandotte_ks,
     "about": "Vacant land bank parcels in Kansas City, Kansas with GIS parcel outlines and acreage."},
    {"id": "shawnee-ks", "name": "Shawnee County / Topeka Parcels For Sale", "agency": "Shawnee County, Kansas",
     "url": SHAWNEE_KS_URL, "state": "KS", "run": shawnee_ks,
     "about": "County-owned vacant parcels for sale in Shawnee County, Kansas with published fixed sale prices and GIS outlines."},
    {"id": "wilmington-de", "name": "City of Wilmington Land Bank Side-Lot Parcels", "agency": "City of Wilmington, Delaware",
     "url": WILMINGTON_DE_URL, "state": "DE", "run": wilmington_de, "historical_only": True,
     "about": "The Wilmington Neighborhood Conservancy Land Bank states that its current sale process is on hold."},
    {"id": "hartford-ct", "name": "City of Hartford City-Owned Vacant Lots", "agency": "City of Hartford, Connecticut",
     "url": HARTFORD_CT_URL, "state": "CT", "run": hartford_ct, "historical_only": True,
     "about": "This city ownership map needs a match to a current sale notice."},
    {"id": "omaha-ne", "name": "City of Omaha City-Owned Vacant Land", "agency": "City of Omaha, Nebraska",
     "url": OMAHA_NE_URL, "state": "NE", "run": omaha_ne, "historical_only": True,
     "about": "This city ownership map needs a match to a current sale or proposal notice."},
    {"id": "bluefield-wv", "name": "City of Bluefield Municipal Land Bank", "agency": "City of Bluefield, West Virginia",
     "url": BLUEFIELD_WV_URL, "state": "WV", "run": bluefield_wv,
     "about": "Municipal Land Bank parcels in Bluefield, West Virginia with GIS outlines, zoning, and acreage."},
    {"id": "memphis-tn", "name": "City of Memphis Surplus Vacant Properties", "agency": "City of Memphis, Tennessee",
     "url": MEMPHIS_TN_URL, "state": "TN", "run": memphis_tn,
     "about": "Surplus vacant city properties in Memphis / Shelby County, Tennessee with GIS outlines and zoning."},
    {"id": "warwick-ri", "name": "City of Warwick Tax-Title Vacant Land", "agency": "City of Warwick, Rhode Island",
     "url": WARWICK_RI_URL, "state": "RI", "run": warwick_ri, "historical_only": True,
     "about": "This land-use layer lacks a current parcel-specific sale or auction notice."},
    {"id": "boston-ma", "name": "City of Boston MOH City-Owned Land", "agency": "City of Boston Mayor's Office of Housing",
     "url": BOSTON_MA_URL, "state": "MA", "run": boston_ma, "historical_only": True,
     "about": "The city custody inventory needs a match to an open land sale or proposal."},
    {"id": "albany-wy", "name": "Albany County 2026 Tax Sale Vacant Land", "agency": "Albany County, Wyoming",
     "url": ALBANY_WY_URL, "state": "WY", "run": albany_wy, "historical_only": True,
     "about": "The 2026 source was a tax lien roll. The county announces its next certificate sale for August 2027."},
    {"id": "odot-ok", "name": "Oklahoma DOT Statewide Surplus Property", "agency": "Oklahoma Department of Transportation",
     "url": ODOT_OK_URL, "state": "OK", "run": odot_ok,
     "about": "Statewide surplus highway right-of-way parcels across Oklahoma counties with GIS outlines, acreage, and PLSS descriptions."},
    {"id": "ms-surplus", "name": "State of Mississippi Surplus Land", "agency": "State of Mississippi Public Lands",
     "url": MS_SURPLUS_URL, "state": "MS", "run": ms_surplus,
     "about": "Unimproved surplus parcels from the State of Mississippi GIS inventory with parcel outlines and acreage."},
    {"id": "horry-sc", "name": "Horry County Delinquent Tax Sale Land", "agency": "Horry County, South Carolina",
     "url": HORRY_SC_URL, "state": "SC", "run": horry_sc, "historical_only": True,
     "about": "The GIS feed comes from the county's 2025 delinquent tax sale. That event has ended."},
    {"id": "portland-or", "name": "City of Portland Vacant City-Owned Land", "agency": "City of Portland, Oregon",
     "url": PORTLAND_OR_URL, "state": "OR", "run": portland_or, "historical_only": True,
     "about": "The city ownership map requires a match to a council-approved active sale."},
    {"id": "maui-hi", "name": "West Maui Vacant Government-Owned Parcels", "agency": "County of Maui / Hawaii Public Lands",
     "url": MAUI_HI_URL, "state": "HI", "run": maui_hi, "historical_only": True,
     "about": "The West Maui government ownership layer needs a match to a current land sale notice."},
    {"id": "lasvegas-nv", "name": "City of Las Vegas Vacant Real Estate Assets", "agency": "City of Las Vegas, Nevada",
     "url": LASVEGAS_NV_URL, "state": "NV", "run": lasvegas_nv, "historical_only": True,
     "about": "The city's real-estate asset layer needs a match to a current land sale notice."},
    {"id": "peterborough-nh", "name": "Town of Peterborough Tax-Deeded Lands", "agency": "Town of Peterborough, New Hampshire",
     "url": PETERBOROUGH_NH_URL, "state": "NH", "run": peterborough_nh, "historical_only": True,
     "about": "The town's tax-deeded holdings need a match to a current sale notice."},
    {"id": "yankton-sd", "name": "City of Yankton Vacant Municipal Lots", "agency": "City of Yankton, South Dakota",
     "url": YANKTON_SD_URL, "state": "SD", "run": yankton_sd, "historical_only": True,
     "about": "The city ownership map needs a match to a current sale notice."},
    {"id": "burleigh-nd", "name": "Burleigh County / Bismarck Vacant Public Land", "agency": "Burleigh County / City of Bismarck, North Dakota",
     "url": BURLEIGH_ND_URL, "state": "ND", "run": burleigh_nd, "historical_only": True,
     "about": "The county and city ownership map needs a match to a current sale notice."},
    {"id": "vcgi-vt", "name": "Vermont Statewide Municipal Vacant Land", "agency": "Vermont Center for Geographic Information (VCGI)",
     "url": VCGI_VT_URL, "state": "VT", "run": vcgi_vt, "historical_only": True,
     "about": "The statewide ownership layer needs a match to individual municipal sale notices."},
    {"id": "montana-cad", "name": "Montana Statewide County & City Vacant Land", "agency": "Montana State Library / County Treasurers",
     "url": MT_CAD_URL, "state": "MT", "run": montana_cad, "historical_only": True,
     "about": "The statewide ownership layer needs a match to current local sale notices."},
    {"id": "boise-id", "name": "City of Boise Housing & Community Development Land", "agency": "City of Boise, Idaho",
     "url": BOISE_ID_URL, "state": "ID", "run": boise_id, "historical_only": True,
     "about": "The community development inventory needs a match to a current sale notice."},
    {"id": "auburn-me", "name": "City of Auburn Unimproved Municipal Land", "agency": "City of Auburn, Maine",
     "url": AUBURN_ME_URL, "state": "ME", "run": auburn_me, "historical_only": True,
     "about": "The city ownership map needs a match to a current sale notice."},
    {"id": "portland-me", "name": "City of Portland Municipal Land Bank", "agency": "City of Portland, Maine",
     "url": PORTLAND_ME_URL, "state": "ME", "run": portland_me, "historical_only": True,
     "about": "The city ownership layer needs a match to a current sale notice."},
    {"id": "wisconsin-bcpl", "name": "Wisconsin Board of Commissioners of Public Lands", "agency": "Wisconsin BCPL",
     "url": WI, "state": "WI", "run": wisconsin, "about": "Surplus state trust land sold by sealed-bid auction or private sale."},
    {"id": "alaska-trust-otc", "name": "Alaska Mental Health Trust Land Office", "agency": "Alaska Mental Health Trust Land Office",
     "url": TRUST, "state": "AK", "run": alaska_trust, "about": "Trust land offered over the counter at fixed prices."},
    {"id": "alaska-dnr", "name": "Alaska Department of Natural Resources land sales", "agency": "Alaska DNR Division of Mining, Land and Water",
     "url": DNR, "state": "AK", "run": alaska_dnr, "about": "State land sold over the counter and by sealed-bid auction."},
    {"id": "utah-udot", "name": "Utah DOT Surplus Real Property", "agency": "Utah Department of Transportation",
     "url": UDOT_URL, "state": "UT", "run": utah_udot, "historical_only": True,
     "about": "The unsold right-of-way inventory needs a match to a current UDOT auction notice."},
    {"id": "california-dgs", "name": "California DGS State Commercial Opportunities", "agency": "California Department of General Services",
     "url": CA_DGS, "state": "CA", "run": california_dgs, "about": "Official state surplus and redevelopment opportunity notices with posted proposal deadlines."},
    {"id": "philly-landbank", "name": "Philadelphia Land Bank vacant lots", "agency": "Philadelphia Land Bank / PHDC",
     "url": PHILLY_LB_URL, "state": "PA", "run": philly_landbank, "requires_sale_match": True,
     "about": "Philadelphia Land Bank parcels marked available on the official sale map and matched to its vacant land layer."},
    {"id": "cleveland-landbank", "name": "City of Cleveland Land Bank vacant land", "agency": "City of Cleveland Land Bank",
     "url": CLEVELAND_LB_URL, "state": "OH", "run": cleveland_landbank,
     "about": "Largest residential, commercial, and industrial vacant lots in the City of Cleveland Land Bank with GIS parcel outlines."},
    {"id": "dallas-landbank", "name": "City of Dallas Land Bank vacant lots", "agency": "City of Dallas Land Bank",
     "url": DALLAS_LB_URL, "state": "TX", "run": dallas_landbank, "historical_only": True,
     "about": "The former feed shows potential Land Bank acquisitions. Its parcels are withheld from active inventory."},
    {"id": "detroit-commercial-land", "name": "City of Detroit Priced Vacant Land For Sale", "agency": "City of Detroit Housing & Revitalization Dept.",
     "url": DETROIT_COMM_URL, "state": "MI", "run": detroit_commercial_land,
     "about": "Fixed-price City of Detroit vacant land parcels for sale with published asking prices and square footage."},
    {"id": "lucas-forfeited-2026", "name": "Lucas County Auditor 2026 Forfeited Land Sale", "agency": "Lucas County Auditor, Ohio",
     "url": LUCAS_FORF_URL, "state": "OH", "run": lucas_forfeited_2026,
     "about": "2026 tax-forfeited land sale parcels in Toledo & Lucas County with delinquent tax opening bids and zoning."},
    {"id": "sauk-county-wi", "name": "Sauk County Tax-Forfeited Land For Sale", "agency": "Sauk County Treasurer, Wisconsin",
     "url": SAUK_WI_URL, "state": "WI", "run": sauk_county_wi,
     "about": "Rural tax-forfeited land parcels open for Offer to Purchase in Sauk County, Wisconsin."},
    {"id": "hoke-county-nc", "name": "Hoke County surplus land bids", "agency": "Hoke County, North Carolina",
     "url": HOKE_NC_URL, "state": "NC", "run": hoke_surplus,
     "about": "Current county surplus land table with parcel IDs, acreage where provided, and official minimum bids."},
    {"id": "wsdot-surplus", "name": "Washington DOT current unimproved surplus lots", "agency": "Washington State Department of Transportation",
     "url": WSDOT_URL, "state": "WA", "run": wsdot_surplus,
     "about": "Current first-come sale listings with no improvements and a published minimum offer."},
    {"id": "itasca-county-mn", "name": "Itasca County over-the-counter tax-forfeited land", "agency": "Itasca County, Minnesota",
     "url": ITASCA_URL, "state": "MN", "run": itasca_otc,
     "about": "Official unimproved tax-forfeited parcels currently offered over the counter with the county's published minimum amount."},
    {"id": "valencia-county-land", "name": "Valencia County available subdivision lots", "agency": "Valencia County Manager, New Mexico",
     "url": VALENCIA_BUY, "state": "NM", "run": valencia_county_land,
     "about": "Unimproved lots from the county parcel map identified through its public land purchase program. Individual prices require a county quote."},
    {"id": "nm-valencia-tax-auction", "name": "New Mexico tax auction notices matched to undeveloped Valencia parcels",
     "agency": "New Mexico Taxation and Revenue Department", "url": NM_PT_URL, "state": "NM", "run": nm_valencia_tax_sale,
     "about": "Future state auction notices with a published minimum bid and a match to an unimproved county parcel."},
    {"id": "stlouis-county-mn", "name": "St. Louis County available tax-forfeited tracts",
     "agency": "St. Louis County Land and Minerals Department, Minnesota", "url": STLOUIS_MN_URL, "state": "MN", "run": stlouis_mn_land,
     "about": "St. Louis County's active available-property booklet for unimproved tracts offered at published prices. Sold and withdrawn tracts are excluded."},
    {"id": "fnsb-chatanika-otc", "name": "Fairbanks North Star Borough West Chatanika over-the-counter lots",
     "agency": "Fairbanks North Star Borough Natural Resources Development", "url": FNSB_SALE, "state": "AK",
     "run": fnsb_chatanika, "about": "Current lot sheets with published West Chatanika prices for over-the-counter purchases."},
    {"id": "south-suburban-landbank", "name": "South Suburban Land Bank available vacant land",
     "agency": "South Suburban Land Bank and Development Authority", "url": SSLBDA_URL, "state": "IL",
     "run": south_suburban_landbank, "requires_sale_match": True,
     "about": "Available residential and commercial lots from the public Land Bank's vacant-land sale directory."},
    {"id": "newburgh-landbank", "name": "Newburgh Community Land Bank available vacant land",
     "agency": "Newburgh Community Land Bank", "url": NEWBURGH_URL, "state": "NY",
     "run": newburgh_landbank, "requires_sale_match": True,
     "about": "Vacant lots in the Land Bank's current sale section. Properties held for other uses or previously sold are excluded."},
    {"id": "salt-lake-county-surplus", "name": "Salt Lake County public surplus land offers",
     "agency": "Salt Lake County Real Estate Division", "url": SLCO_SALE, "state": "UT",
     "run": salt_lake_county_surplus, "requires_sale_match": True, "timezone": "America/Denver",
     "about": "Active county surplus offers matched to assessor parcels with zero recorded building value."},
    {"id": "muncie-landbank", "name": "Muncie Land Bank vacant lot auctions",
     "agency": "Muncie Land Bank", "url": MUNCIE_VACANT, "state": "IN",
     "run": muncie_landbank, "requires_sale_match": True,
     "about": "Active vacant land auctions with an open bid form, a future deadline, and a published minimum bid."},
    {"id": "harris-county-tax-sales", "name": "Harris County tax auctions for unimproved land",
     "agency": "Harris County Tax Assessor-Collector", "url": HARRIS_SALE, "state": "TX",
     "run": harris_county_tax_sales, "requires_sale_match": True, "timezone": "America/Chicago",
     "about": "County sale cards marked For Sale, matched to vacant HCAD land classes with zero recorded building and improvement value."},
    {"id": "glynn-brunswick-landbank", "name": "Glynn-Brunswick available land bank lots",
     "agency": "Glynn-Brunswick Land Bank Authority", "url": GLYNN_SALE, "state": "GA",
     "run": glynn_brunswick_landbank, "requires_sale_match": True,
     "about": "Priced vacant lots published as available. Properties under foreclosure or containing structures are excluded."},
    {"id": "king-county-current-surplus", "name": "King County current vacant surplus sale notices",
     "agency": "King County Real Estate Services", "url": KING_SURPLUS, "state": "WA",
     "run": king_county_surplus, "requires_sale_match": True,
     "about": "Vacant parcels with published asking prices on the county's current surplus sale page."},
    {"id": "caltrans-surplus", "name": "Caltrans unimproved land auctions",
     "agency": "California Department of Transportation", "url": CALTRANS_LAND, "state": "CA",
     "run": caltrans_surplus, "requires_sale_match": True,
     "about": "Current sealed-bid land auction brochures with a published minimum bid and a future bid deadline."},
    {"id": "massachusetts-land-for-homes", "name": "Massachusetts State Land for Homes private development auctions",
     "agency": "Massachusetts Division of Capital Asset Management and Maintenance", "url": MA_LAND_FOR_HOMES, "state": "MA",
     "run": massachusetts_land_for_homes, "requires_sale_match": True, "timezone": "America/New_York",
     "about": "Vacant land in the Commonwealth's upcoming public housing-development auctions. Follow the official notice for auction terms."},
    {"id": "lakota-nd-lots", "name": "Lakota, North Dakota municipal housing lots",
     "agency": "City of Lakota, North Dakota", "url": LAKOTA_ND_LOTS, "state": "ND",
     "run": lakota_nd_lots, "requires_sale_match": True,
     "about": "City lots listed as for sale with the city's per-square-foot price applied to the published subdivision plat."},
    {"id": "princeton-mn-lots", "name": "Princeton, Minnesota municipal development lots",
     "agency": "City of Princeton, Minnesota", "url": PRINCETON_MN_SALE, "state": "MN",
     "run": princeton_mn_lots, "requires_sale_match": True,
     "about": "City and economic development authority industrial and commercial lots currently posted for sale."},
    {"id": "burlington-ia-lots", "name": "Burlington, Iowa vacant city lots for sale",
     "agency": "City of Burlington, Iowa", "url": BURLINGTON_IA_SALE, "state": "IA",
     "run": burlington_ia_lots, "requires_sale_match": True,
     "about": "Parcels on the city's active vacant lot sale list. Review city bidding and construction requirements."},
    {"id": "desoto-fl-auctions", "name": "DeSoto County, Florida vacant tax deed auctions",
     "agency": "DeSoto County Clerk of the Circuit Court and Comptroller", "url": DESOTO_FL_SALE, "state": "FL",
     "run": desoto_fl_auctions, "requires_sale_match": True,
     "about": "Scheduled tax deed sales with a published opening bid, matched by parcel number to vacant Florida assessment records with no buildings."},
    {"id": "greenburgh-ny-auctions", "name": "Greenburgh, New York town tax foreclosure land auctions",
     "agency": "Town of Greenburgh, New York", "url": GREENBURGH_NY_NOTICE, "state": "NY",
     "run": greenburgh_ny_auctions, "requires_sale_match": True,
     "about": "Vacant residential land in the town's linked auction catalog with published starting bids and individual closing times."},
    {"id": "rochester-ny-environmental", "name": "Rochester, New York environmental foreclosure land auction",
     "agency": "City of Rochester Finance Department", "url": ROCHESTER_NY_SALE, "state": "NY",
     "run": rochester_ny_environmental, "requires_sale_match": True, "timezone": "America/New_York",
     "about": "Vacant land in the city's environmental auction with known or suspected contamination. The city's estimated minimum bids are shown in the parcel facts."},
]
NOT_CARRIED = [
    ("City of Durham surplus property listings", "https://www.durhamnc.gov/810/Surplus-Properties",
     "The city robots.txt endpoint returned HTTP 403."),
    ("Florida RealTaxDeed auction catalogs", "https://volusia.realtaxdeed.com/",
     "The Lee, Polk, Volusia and Washington county auction portals returned HTTP 403 for robots.txt."),
    ("Scribner's linked LocationOne inventory", "https://www.scribner-ne.gov/lots-for-sale/",
     "The city lists an overall price and number of available lots. Its linked inventory returned HTML at robots.txt and was skipped."),
    ("Henderson, Nebraska Highland Addition lots", "https://www.cityofhenderson.org/highland-addition/",
     "The city site did not serve a verifiable HTTPS certificate for robots.txt."),
    ("Los Angeles County 2026B follow-up auction", "https://ttc.lacounty.gov/schedule-of-upcoming-auctions/",
     "The county links to a separate GovEase catalog for this sale. Its robots.txt disallows the listing path."),
    ("Navajo County back-tax auction notice", "https://www.navajocountyaz.gov/197/Back-Tax-Land",
     "The county robots.txt endpoint returned HTTP 403. The prior GIS auction catalog could not verify the upcoming sale."),
    ("Spokane County foreclosure listings", "https://www.spokanecounty.gov/4156/Real-Property-Auctions",
     "The county robots.txt endpoint returned HTTP 403."),
    ("Miami-Dade public surplus land", "https://www.miamidade.gov/global/strategic-procurement/real-estate.page",
     "The public listing pages returned HTTP 403 to automated reads."),
    ("Nevada DOT surplus land", "https://www.dot.nv.gov/doing-business/right-of-way/surplus-property-sales",
     "Automated reads are skipped because the site's robots.txt returned HTTP 403."),
    ("Macon-Bibb Land Bank inventory", "https://maconlandbank.org/available-inventory/",
     "The sale page identifies the official price, but robots.txt disallows the table endpoint that contains the individual properties."),
    ("Shelby County, Cook County, Metro Atlanta, Waterbury and Greater Syracuse land bank portals",
     "https://www.shelbycountytrustee.com/198/Shelby-County-Land-Bank",
     "The linked listing portals could not serve their robots.txt files over HTTPS. Browse the public agency links directly."),
    ("Omaha and Birmingham Land Bank portal maps", "https://omahalandbank.org/property-sales/",
     "The linked listing portals returned HTML instead of crawler rules at their robots.txt endpoints."),
    ("Gadsden Land Bank catalog", "https://www.gadsdenlandbank.org/",
     "The catalog is excluded by the official site's robots.txt."),
    ("Onslow County public surplus land", "https://www.onslowcountync.gov/DocumentCenter/View/6669/SURPLUS-LAND-FOR-WEBSITE-",
     "Automated reads are skipped because the agency's robots.txt returned HTTP 403."),
    ("BuyIntoBmore and Dallas Land Bank public portals", "https://buyintobmore.baltimorecity.gov/",
     "Automated reads skipped because both listing portals returned HTML instead of crawler rules at their robots.txt endpoints."),
    ("Kenai Peninsula Borough land sales", "https://www.kpb.us/landmgt/landsales",
     "Automated reads are skipped because the official robots.txt endpoint returned HTML instead of crawler rules."),
    ("Arizona DOT and Arizona State Land Department sales", "https://azdot.gov/business/right-way-properties/vacant-land-and-commercial-properties-sale",
     "Automated reads are skipped because the robots.txt endpoints returned HTTP 403. Browse the agency property notices directly."),
    ("West Virginia State Auditor County Collections", "https://main.wvsao.gov/CountyCollections/",
     "Automated reads are skipped because the site's robots.txt route returned HTML instead of crawler rules."),
    ("Orange County Comptroller lands available for taxes", "https://www.occompt.com/158/Land-Available-For-Taxes",
     "The Comptroller page's robots.txt could not be read. Browse its lands-available list directly."),
    ("GovDeals and Bid4Assets listings", "https://www.govdeals.com/",
     "Automated reads were skipped when these auction services' robots.txt endpoints returned HTTP 403."),
    ("City of Dallas potential Land Bank acquisitions", "https://citysecretary2.dallascityhall.com/resolutions/2026/02-25-26/26-0395.pdf",
     "The City's annual-plan map shows lots eligible for acquisition by the Land Bank. It does not identify lots currently offered for purchase."),
    ("GSA RealEstateSales.gov (federal surplus)", "https://realestatesales.gov/",
     "Not crawled: its robots.txt disallows automated access. Browse it directly."),
    ("BLM public land sales", "https://www.blm.gov/programs/lands-and-realty/land-tenure/land-sales",
     "Sale notices are published irregularly as press announcements; planned for future ingestion."),
    ("Utah SITLA & Washington DNR Trust Land GIS", "https://trustlands.utah.gov/",
     "Transaction ArcGIS folders currently require authentication tokens; browse agency auction calendars directly."),
    ("City of Milwaukee DCD Real Estate GIS", "https://city.milwaukee.gov/DCD/CityRealEstate",
     "Not crawled: milwaukeemaps.milwaukee.gov robots.txt disallows automated access. Browse city.milwaukee.gov directly."),
]
