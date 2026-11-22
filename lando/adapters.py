"""One adapter per official source. Each returns (listings, info) or raises when the source's structure changed.

Every listing links to its official source page. Only facts about the land and the offering are kept: no names of
previous owners, no photographs, no marketing text. Prices are never invented: a source without a price gets none.

    listing = {id, source, title, state, county, locality, apn, acres, price, price_kind, offering, status,
               deadline, url, address, lat, lon, geometry, facts, tags}
"""
import csv
import datetime
import html
import io
import re
import urllib.parse

from .net import FetchError

STATUS = {  # status -> (label, still available to buy)
    "listed": ("Listed by the agency", True),
    "auction_open": ("Auction: bidding open", True),
    "auction_terms": ("Auction or tax sale: see terms", True),
    "proposal_open": ("Proposals invited", True),
    "pending": ("Sale pending", False),
    "auction_closed": ("Bidding closed", False),
}
PRICE_KIND = {"cash": "Price", "min_bid": "Minimum bid", "none": "No price published"}


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
    return ""


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


def parse_st_louis(available_csv, inventory_csv, warn):
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
        facts = [
            fact("availability", "Available", "@stl_inventory",
                 "stl_available"),
            fact("lot_area", "%s square feet" % ("{:,}".format(int(sqft)) if sqft else "not listed"),
                 "@stl_available", "stl_area"),
            fact("price", "No asking price in the city's export", "@stl_available", "stl_price"),
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
            "acres": round(sqft / 43560.0, 4) if sqft else None, "price": None, "price_kind": "none", "offering": "sale",
            "status": "listed", "deadline": None, "url": url, "address": clean(r["Address"]).title(),
            "lat": None, "lon": None, "geometry": None, "facts": facts,
            "tags": ["city-owned vacant lot", "application required"],
        })
    return out


def st_louis(fetch, now, warn):
    rows = parse_st_louis(fetch.text(STL + "LRA_INVENTORY_AVAILABLE.csv"), fetch.text(STL + "LRA_INVENTORY.csv"), warn)
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


URLS.update({"stl_inventory": STL + "LRA_INVENTORY.csv", "stl_available": STL + "LRA_INVENTORY_AVAILABLE.csv"})

SOURCES = [
    {"id": "st-louis-lra", "name": "City of St. Louis vacant-lot inventory", "agency": "St. Louis Development Corporation / Land Reutilization Authority",
     "url": "https://www.stlouis-mo.gov/government/departments/sldc/real-estate/lra-owned-property-search.cfm", "state": "MO", "run": st_louis,
     "about": "City-owned vacant lots marked available in the city's open-data exports. No prices are published; buying goes through the city's application."},
    {"id": "arkansas-cosl", "name": "Arkansas Commissioner of State Lands", "agency": "Arkansas Commissioner of State Lands",
     "url": "https://auction.cosl.org/Auctions/ListingsView", "state": "AR", "run": arkansas,
     "about": "Tax-forfeited parcels offered after the county tax-sale auctions. Prices are minimum bids; terms and redemption rules apply."},
    {"id": "wisconsin-bcpl", "name": "Wisconsin Board of Commissioners of Public Lands", "agency": "Wisconsin BCPL",
     "url": WI, "state": "WI", "run": wisconsin, "about": "Surplus state trust land sold by sealed-bid auction or private sale."},
    {"id": "alaska-trust-otc", "name": "Alaska Mental Health Trust Land Office", "agency": "Alaska Mental Health Trust Land Office",
     "url": TRUST, "state": "AK", "run": alaska_trust, "about": "Trust land offered over the counter at fixed prices."},
    {"id": "alaska-dnr", "name": "Alaska Department of Natural Resources land sales", "agency": "Alaska DNR Division of Mining, Land and Water",
     "url": DNR, "state": "AK", "run": alaska_dnr, "about": "State land sold over the counter and by sealed-bid auction."},
]
NOT_CARRIED = [
    ("GSA RealEstateSales.gov (federal surplus)", "https://realestatesales.gov/",
     "Not crawled: its robots.txt disallows automated access. Browse it directly."),
    ("California DGS surplus and site opportunities", "https://www.dgs.ca.gov/RESD/Projects/Page-Content/Projects-List-Folder/State-Commercial-Opportunities-Portal",
     "Occasional proposal notices with deadlines; not yet carried over from the original application."),
    ("BLM public land sales", "https://www.blm.gov/programs/lands-and-realty/land-tenure/land-sales",
     "Sale notices are published irregularly as press announcements; not yet carried over."),
]
