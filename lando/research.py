"""Deterministic public-agency rural & municipal land statistics computed directly from Catalog."""
import statistics

from . import adapters, config
from .model import STATE_NAMES

PRICE_BRACKETS = (
    ("Under $250", lambda p: p < 250),
    ("$250 - $999", lambda p: 250 <= p < 1000),
    ("$1,000 - $4,999", lambda p: 1000 <= p < 5000),
    ("$5,000 - $24,999", lambda p: 5000 <= p < 25000),
    ("$25,000 - $99,999", lambda p: 25000 <= p < 100000),
    ("$100,000+", lambda p: p >= 100000),
)

ACREAGE_BRACKETS = (
    ("Under 0.25 acres (city & subdivision lots)", lambda a: a < 0.25),
    ("0.25 - 0.99 acres", lambda a: 0.25 <= a < 1.0),
    ("1.0 - 4.99 acres", lambda a: 1.0 <= a < 5.0),
    ("5.0 - 19.99 acres", lambda a: 5.0 <= a < 20.0),
    ("20.0 - 49.99 acres", lambda a: 20.0 <= a < 50.0),
    ("50.0+ acres", lambda a: a >= 50.0),
)


def fmt_money(v, dash="None published"):
    if v is None:
        return dash
    return "$" + ("{:,.2f}".format(v) if abs(v - round(v)) >= 0.005 else "{:,}".format(int(round(v))))


def fmt_money_exact(v, dash="None published"):
    if v is None:
        return dash
    return "${:,.2f}".format(v)


def fmt_acres(v):
    if v is None or v <= 0:
        return "0"
    if v >= 100:
        return "{:,.2f}".format(v)
    return ("{:,.2f}".format(v)).rstrip("0").rstrip(".")


def fmt_pct(num, den):
    if not den:
        return 0.0
    return round((num / float(den)) * 100.0, 1)


def _median(vals):
    return round(statistics.median(vals), 2) if vals else None


def _mean(vals):
    return round(statistics.mean(vals), 2) if vals else None


def compute_benchmarks(cat):
    """Compute every statistical benchmark strictly from active catalog rows on disk."""
    cur = cat.current()
    updated = (cat.status.get("checked") or cat.now.strftime("%Y-%m-%d"))[:10]
    active_count = len(cur)
    total_tracked = len(cat.listings)

    with_acres = [r for r in cur if r.get("acres") and r["acres"] > 0]
    with_price = [r for r in cur if r.get("price") is not None and r["price"] > 0]
    with_both = [r for r in cur if r.get("price") is not None and r["price"] > 0 and r.get("acres") and r["acres"] > 0]

    acres_vals = [r["acres"] for r in with_acres]
    price_vals = [r["price"] for r in with_price]
    ppa_vals = [r["price"] / r["acres"] for r in with_both]

    total_acres = round(sum(acres_vals), 2)
    median_acres = _median(acres_vals)
    mean_acres = _mean(acres_vals)
    median_price = _median(price_vals)
    mean_price = _mean(price_vals)
    median_ppa = _median(ppa_vals)
    mean_ppa = _mean(ppa_vals)

    # Price disclosure kinds
    kind_counts = {"none": 0, "min_bid": 0, "cash": 0}
    for r in cur:
        k = r.get("price_kind") or "none"
        kind_counts[k] = kind_counts.get(k, 0) + 1

    fixed_rows = [r for r in cur if r.get("price_kind") == "cash" and r.get("price") is not None and r["price"] > 0]
    fixed_both = [r for r in fixed_rows if r.get("acres") and r["acres"] > 0]
    fixed_acres = round(sum(r["acres"] for r in fixed_both), 2)
    fixed_median_price = _median([r["price"] for r in fixed_rows])
    fixed_median_ppa = _median([r["price"] / r["acres"] for r in fixed_both])

    # State benchmarks
    states = []
    for st in sorted(cat.states.values(), key=lambda s: (-sum(1 for r in s["listings"] if r["available"]), s["name"])):
        ac = [r for r in st["listings"] if r["available"]]
        if not ac:
            continue
        wa = [r["acres"] for r in ac if r.get("acres") and r["acres"] > 0]
        wp = [r["price"] for r in ac if r.get("price") is not None and r["price"] > 0]
        wb = [r["price"] / r["acres"] for r in ac if r.get("price") is not None and r["price"] > 0 and r.get("acres") and r["acres"] > 0]
        active_counties = sum(1 for c in st["counties"].values() if any(r["available"] for r in c["listings"]))
        kinds = sorted({adapters.PRICE_KIND.get(r["price_kind"], "No price published") for r in ac})
        states.append({
            "code": st["code"],
            "name": st["name"],
            "path": cat.state_path(st),
            "active_count": len(ac),
            "share_pct": fmt_pct(len(ac), active_count),
            "county_count": active_counties,
            "acres_count": len(wa),
            "total_acres": round(sum(wa), 2),
            "median_acres": _median(wa),
            "priced_count": len(wp),
            "median_price": _median(wp),
            "mean_price": _mean(wp),
            "min_price": round(min(wp), 2) if wp else None,
            "max_price": round(max(wp), 2) if wp else None,
            "both_count": len(wb),
            "median_ppa": _median(wb),
            "mean_ppa": _mean(wb),
            "pricing_summary": ", ".join(kinds),
        })

    # Agency breakdown (official sources with active listings)
    agencies = []
    by_src = {}
    for r in cur:
        by_src.setdefault(r["source"], []).append(r)
    for src in adapters.SOURCES:
        ac = by_src.get(src["id"], [])
        if not ac:
            continue
        wa = [r["acres"] for r in ac if r.get("acres") and r["acres"] > 0]
        wp = [r["price"] for r in ac if r.get("price") is not None and r["price"] > 0]
        wb = [r["price"] / r["acres"] for r in ac if r.get("price") is not None and r["price"] > 0 and r.get("acres") and r["acres"] > 0]
        status_entry = cat.status.get("sources", {}).get(src["id"], {})
        kinds = sorted({adapters.PRICE_KIND.get(r["price_kind"], "No price published") for r in ac})
        agencies.append({
            "id": src["id"],
            "agency": src["agency"],
            "name": src["name"],
            "state": src["state"],
            "state_name": STATE_NAMES.get(src["state"], src["state"]),
            "url": src["url"],
            "about": src["about"],
            "active_count": len(ac),
            "share_pct": fmt_pct(len(ac), active_count),
            "acres_count": len(wa),
            "total_acres": round(sum(wa), 2),
            "priced_count": len(wp),
            "median_price": _median(wp),
            "both_count": len(wb),
            "median_ppa": _median(wb),
            "mean_ppa": _mean(wb),
            "pricing_summary": ", ".join(kinds),
            "last_read": (status_entry.get("last_success") or updated)[:10],
        })
    agencies.sort(key=lambda a: (-a["active_count"], a["agency"]))

    # Top 10 counties / jurisdictions by active listing count
    all_counties = []
    for st in cat.states.values():
        for c in st["counties"].values():
            ac = [r for r in c["listings"] if r["available"]]
            if not ac:
                continue
            wa = [r["acres"] for r in ac if r.get("acres") and r["acres"] > 0]
            wp = [r["price"] for r in ac if r.get("price") is not None and r["price"] > 0]
            wb = [r["price"] / r["acres"] for r in ac if r.get("price") is not None and r["price"] > 0 and r.get("acres") and r["acres"] > 0]
            all_counties.append({
                "name": c["name"],
                "state_code": st["code"],
                "state_name": st["name"],
                "path": cat.county_path(st, c),
                "active_count": len(ac),
                "share_pct": fmt_pct(len(ac), active_count),
                "acres_count": len(wa),
                "total_acres": round(sum(wa), 2),
                "priced_count": len(wp),
                "median_price": _median(wp),
                "both_count": len(wb),
                "median_ppa": _median(wb),
            })
    all_counties.sort(key=lambda c: (-c["active_count"], c["state_name"], c["name"]))
    top_counties = all_counties[:10]

    # Price brackets
    price_brackets = []
    for label, pred in PRICE_BRACKETS:
        cnt = sum(1 for r in with_price if pred(r["price"]))
        price_brackets.append({
            "label": label,
            "count": cnt,
            "pct": fmt_pct(cnt, len(with_price)),
        })

    # Acreage brackets
    acreage_brackets = []
    for label, pred in ACREAGE_BRACKETS:
        matches = [r for r in with_acres if pred(r["acres"])]
        sub_acres = round(sum(r["acres"] for r in matches), 2)
        acreage_brackets.append({
            "label": label,
            "count": len(matches),
            "pct": fmt_pct(len(matches), len(with_acres)),
            "acres": sub_acres,
            "acres_pct": fmt_pct(sub_acres, total_acres),
        })

    # Extremes
    largest_parcel = max(with_acres, key=lambda r: (r["acres"], r["id"])) if with_acres else None
    lowest_priced = min(with_price, key=lambda r: (r["price"], r["id"])) if with_price else None
    highest_priced = max(with_price, key=lambda r: (r["price"], r["id"])) if with_price else None

    large_20plus = [r for r in with_acres if r["acres"] >= 20.0]
    large_20plus_acres = round(sum(r["acres"] for r in large_20plus), 2)
    under_quarter = [r for r in with_acres if r["acres"] < 0.25]
    under_quarter_acres = round(sum(r["acres"] for r in under_quarter), 2)

    state_by_code = {s["code"]: s for s in states}
    agency_by_id = {a["id"]: a for a in agencies}
    county_total = len(all_counties)

    # Standalone, citable finding sentences (10 on production catalog; adapts cleanly to smaller test fixtures)
    findings = []
    if active_count > 0:
        findings.append({
            "id": "active-public-inventory",
            "label": "Active public inventory",
            "metric": "{:,} offerings".format(active_count),
            "sentence": (
                "As of %s, Landosaur tracks %s active public-agency land offerings across %d U.S. %s, %d %s, "
                "and %d official government %s (snapshot from %s total stored records)."
            ) % (
                updated, "{:,}".format(active_count), len(states),
                "state" if len(states) == 1 else "states", county_total,
                "county or jurisdiction" if county_total == 1 else "counties and jurisdictions",
                len(agencies), "source" if len(agencies) == 1 else "sources", "{:,}".format(total_tracked),
            ),
        })
        findings.append({
            "id": "pricing-disclosure-split",
            "label": "Pricing disclosure structure",
            "metric": "%s%% unpriced / %s%% bid" % (
                fmt_pct(kind_counts.get("none", 0), active_count),
                fmt_pct(kind_counts.get("min_bid", 0), active_count),
            ),
            "sentence": (
                "Across all %s active public-agency listings as of %s, %s (%.1f%%) publish no asking price (offer-based municipal inventory), "
                "%s (%.1f%%) publish an auction minimum bid, and %s (%.1f%%) publish a fixed over-the-counter price."
            ) % (
                "{:,}".format(active_count), updated,
                "{:,}".format(kind_counts.get("none", 0)), fmt_pct(kind_counts.get("none", 0), active_count),
                "{:,}".format(kind_counts.get("min_bid", 0)), fmt_pct(kind_counts.get("min_bid", 0), active_count),
                "{:,}".format(kind_counts.get("cash", 0)), fmt_pct(kind_counts.get("cash", 0), active_count),
            ),
        })

    if with_acres:
        findings.append({
            "id": "total-published-acreage",
            "label": "Published acreage & concentration",
            "metric": "%s acres" % fmt_acres(total_acres),
            "sentence": (
                "The %s active offerings that report parcel area total %s acres (snapshot %s), with %s small lots under 0.25 acres "
                "accounting for %.1f%% of acreage-reported listings (%s acres), while %s tracts of 20 acres or more (%.2f%% of listings) "
                "account for %s acres (%.1f%% of all published acreage)."
            ) % (
                "{:,}".format(len(with_acres)), fmt_acres(total_acres), updated,
                "{:,}".format(len(under_quarter)), fmt_pct(len(under_quarter), len(with_acres)), fmt_acres(under_quarter_acres),
                "{:,}".format(len(large_20plus)), round((len(large_20plus) / float(len(with_acres))) * 100.0, 2),
                fmt_acres(large_20plus_acres), fmt_pct(large_20plus_acres, total_acres),
            ),
        })

    if with_both:
        findings.append({
            "id": "overall-price-per-acre",
            "label": "Overall price-per-acre benchmark",
            "metric": "%s / acre median" % fmt_money_exact(median_ppa),
            "sentence": (
                "Among the %s active public offerings that publish both a positive price or minimum bid and parcel acreage (as of %s), "
                "the overall median implied price per acre is %s and the mean is %s per acre."
            ) % (
                "{:,}".format(len(with_both)), updated, fmt_money_exact(median_ppa), fmt_money_exact(mean_ppa),
            ),
        })

    if with_price:
        under_250 = price_brackets[0]
        over_100k = price_brackets[-1]
        findings.append({
            "id": "price-distribution-skew",
            "label": "Published price & bid distribution",
            "metric": "%s median (%s%% < $250)" % (fmt_money_exact(median_price), under_250["pct"]),
            "sentence": (
                "Across all %s active listings with a published price or minimum bid (%s snapshot), the median published figure is %s "
                "(mean %s), ranging from %s (%s) to %s (%s); %s listings (%.1f%%) start under $250 while %s (%.1f%%) are priced at $100,000 or above."
            ) % (
                "{:,}".format(len(with_price)), updated, fmt_money_exact(median_price), fmt_money_exact(mean_price),
                fmt_money_exact(lowest_priced["price"]), lowest_priced["county_label"] + ", " + lowest_priced["state"],
                fmt_money_exact(highest_priced["price"]), highest_priced["county_label"] + ", " + highest_priced["state"],
                "{:,}".format(under_250["count"]), under_250["pct"],
                "{:,}".format(over_100k["count"]), over_100k["pct"],
            ),
        })

    if "WI" in state_by_code and state_by_code["WI"]["both_count"]:
        wi = state_by_code["WI"]
        avg_wi_ac = round(wi["total_acres"] / float(wi["acres_count"]), 2) if wi["acres_count"] else 0
        findings.append({
            "id": "wisconsin-rural-benchmark",
            "label": "Wisconsin rural trust land",
            "metric": "%s / acre median" % fmt_money_exact(wi["median_ppa"]),
            "sentence": (
                "Wisconsin Board of Commissioners of Public Lands (BCPL) accounts for the largest rural acreage pool among priced agencies as of %s: "
                "%s active parcels totaling %s acres (mean %.2f acres per parcel) at a median price of %s and a median of %s per acre (mean %s per acre)."
            ) % (
                updated, "{:,}".format(wi["active_count"]), fmt_acres(wi["total_acres"]), avg_wi_ac,
                fmt_money(wi["median_price"]), fmt_money_exact(wi["median_ppa"]), fmt_money_exact(wi["mean_ppa"]),
            ),
        })

    if "AR" in state_by_code and state_by_code["AR"]["priced_count"]:
        ar = state_by_code["AR"]
        findings.append({
            "id": "arkansas-tax-sale-benchmark",
            "label": "Arkansas tax-forfeited auctions",
            "metric": "%s median min bid" % fmt_money_exact(ar["median_price"]),
            "sentence": (
                "Arkansas Commissioner of State Lands (COSL) lists %s active tax-forfeited parcels across %d counties as of %s with a median "
                "minimum bid of %s (mean %s); among the %s Arkansas listings reporting both minimum bid and acreage (%s total acres), "
                "the median minimum bid per acre is %s."
            ) % (
                "{:,}".format(ar["active_count"]), ar["county_count"], updated,
                fmt_money_exact(ar["median_price"]), fmt_money_exact(ar["mean_price"]),
                "{:,}".format(ar["both_count"]), fmt_acres(ar["total_acres"]),
                fmt_money_exact(ar["median_ppa"]),
            ),
        })

    if "AK" in state_by_code and state_by_code["AK"]["both_count"]:
        ak = state_by_code["AK"]
        ak_trust = agency_by_id.get("alaska-trust-otc")
        ak_dnr = agency_by_id.get("alaska-dnr")
        extra_ak = ""
        if ak_trust and ak_dnr and ak_trust["median_ppa"] is not None and ak_dnr["median_ppa"] is not None:
            extra_ak = " — spanning %s per acre on Alaska DNR's %s-acre parcel and a median of %s per acre across %s Alaska Mental Health Trust OTC lots" % (
                fmt_money_exact(ak_dnr["median_ppa"]), fmt_acres(ak_dnr["total_acres"]),
                fmt_money_exact(ak_trust["median_ppa"]), "{:,}".format(ak_trust["active_count"]),
            )
        findings.append({
            "id": "alaska-state-trust-benchmark",
            "label": "Alaska state & trust OTC land",
            "metric": "%s / acre median" % fmt_money_exact(ak["median_ppa"]),
            "sentence": (
                "Alaska's %s active over-the-counter state and trust land offerings total %s acres as of %s, carrying a median fixed price of %s "
                "and a median of %s per acre (mean %s per acre)%s."
            ) % (
                "{:,}".format(ak["active_count"]), fmt_acres(ak["total_acres"]), updated,
                fmt_money(ak["median_price"]), fmt_money_exact(ak["median_ppa"]), fmt_money_exact(ak["mean_ppa"]), extra_ak,
            ),
        })

    if top_counties and len(top_counties) >= 2:
        c1, c2 = top_counties[0], top_counties[1]
        top3_total = sum(c["active_count"] for c in top_counties[:3])
        findings.append({
            "id": "top-county-concentration",
            "label": "County listing concentration",
            "metric": "%s%% in top 3 jurisdictions" % fmt_pct(top3_total, active_count),
            "sentence": (
                "%s, %s holds the largest active inventory in the catalog with %s public listings (%.1f%% of all %s active offerings as of %s), "
                "followed by %s, %s (%s listings, %.1f%%); the top three jurisdictions together represent %s listings (%.1f%%)."
            ) % (
                c1["name"], c1["state_code"], "{:,}".format(c1["active_count"]), c1["share_pct"],
                "{:,}".format(active_count), updated,
                c2["name"], c2["state_code"], "{:,}".format(c2["active_count"]), c2["share_pct"],
                "{:,}".format(top3_total), fmt_pct(top3_total, active_count),
            ),
        })

    if largest_parcel:
        findings.append({
            "id": "largest-public-tract",
            "label": "Largest active public parcel",
            "metric": "%s acres" % fmt_acres(largest_parcel["acres"]),
            "sentence": (
                "The largest individual active tract in the %s snapshot is %s in %s, %s at %s acres%s."
            ) % (
                updated, largest_parcel["title"], largest_parcel["county_label"], largest_parcel["state_name"],
                fmt_acres(largest_parcel["acres"]),
                (" (published at %s, or %s per acre)" % (
                    fmt_money(largest_parcel["price"]),
                    fmt_money_exact(largest_parcel["price"] / largest_parcel["acres"]),
                )) if largest_parcel.get("price") else "",
            ),
        })

    # 6 truthful FAQs for /research/ (verbatim match with FAQPage JSON-LD)
    wi_note = ""
    if "WI" in state_by_code and state_by_code["WI"]["median_ppa"] is not None:
        wi_note = " In Wisconsin (n = %s BCPL parcels, %s acres), the median is %s per acre." % (
            "{:,}".format(state_by_code["WI"]["both_count"]), fmt_acres(state_by_code["WI"]["total_acres"]),
            fmt_money_exact(state_by_code["WI"]["median_ppa"]),
        )
    ar_note = ""
    if "AR" in state_by_code and state_by_code["AR"]["median_ppa"] is not None:
        ar_note = " In Arkansas (n = %s COSL parcels reporting both bid and area), the median minimum bid is %s per acre." % (
            "{:,}".format(state_by_code["AR"]["both_count"]), fmt_money_exact(state_by_code["AR"]["median_ppa"]),
        )
    ak_note = ""
    if "AK" in state_by_code and state_by_code["AK"]["median_ppa"] is not None:
        ak_note = " In Alaska (n = %s OTC parcels), the median fixed price is %s per acre." % (
            "{:,}".format(state_by_code["AK"]["both_count"]), fmt_money_exact(state_by_code["AK"]["median_ppa"]),
        )

    research_faqs = [
        (
            "What is the median price per acre for public-agency land on Landosaur?",
            (
                "As of %s, across the %s active public-agency offerings that publish both a positive price or minimum bid and parcel acreage, "
                "the overall median is %s per acre (mean %s per acre).%s%s%s"
            ) % (
                updated, "{:,}".format(len(with_both)), fmt_money_exact(median_ppa), fmt_money_exact(mean_ppa),
                wi_note, ar_note, ak_note,
            ) if with_both else (
                "Price-per-acre benchmarks are computed only from active offerings where the agency publishes both a positive price or minimum bid and parcel acreage. "
                "None of the currently indexed listings publish both fields in this snapshot (%s)." % updated
            ),
        ),
        (
            "How many active government land offerings and acres are in this benchmark?",
            "The %s snapshot contains %s active public-agency offerings across %d U.S. %s, %d %s, and %d official government agencies. "
            "Exactly %s active listings publish parcel area, totaling %s acres; agencies that omit acreage on subdivision tax lots are excluded from acreage totals rather than estimated." % (
                updated, "{:,}".format(active_count), len(states), "state" if len(states) == 1 else "states",
                county_total, "county or jurisdiction" if county_total == 1 else "counties and jurisdictions",
                len(agencies), "{:,}".format(len(with_acres)), fmt_acres(total_acres),
            ),
        ),
        (
            "Why do most active listings on Landosaur show no published price?",
            "Exactly %s of %s active offerings (%.1f%%) publish no asking price because municipal land banks such as the St. Louis Land Reutilization Authority "
            "accept buyer offers directly rather than posting list prices. Landosaur never invents or estimates asking prices where the source agency publishes none." % (
                "{:,}".format(kind_counts.get("none", 0)), "{:,}".format(active_count),
                fmt_pct(kind_counts.get("none", 0), active_count),
            ),
        ),
        (
            "What is the difference between a minimum bid and a fixed price in these statistics?",
            "Auction minimum bids (%s active listings, %.1f%%) represent opening bid floors set by tax-forfeited land agencies such as Arkansas COSL—not final closing prices. "
            "Fixed prices (%s active listings, %.1f%%) represent published over-the-counter or sealed-bid asking prices from state trust land agencies in Wisconsin and Alaska." % (
                "{:,}".format(kind_counts.get("min_bid", 0)), fmt_pct(kind_counts.get("min_bid", 0), active_count),
                "{:,}".format(kind_counts.get("cash", 0)), fmt_pct(kind_counts.get("cash", 0), active_count),
            ),
        ),
        (
            "How fresh are these public land statistics and how are sold parcels removed?",
            "The latest source snapshot was read on %s. If a source read fails or returns partial data, Landosaur preserves the last verified snapshot. "
            "A listing is withdrawn only after two consecutive complete agency reads omit it, and any source unchecked for %d days leaves the active catalog." % (
                updated, config.CURRENT_DAYS,
            ),
        ),
        (
            "Can researchers and journalists download the underlying public-land data?",
            "Yes. Every benchmark on this page is computed deterministically from the open Landosaur catalog, available for free download as listings.csv, map.json, sources.json, and Atom XML feeds. "
            "Every record links back to its authoritative government agency URL; Landosaur does not broker land or provide legal, title, or tax advice.",
        ),
    ]

    # 6 truthful FAQs for the Homepage `/` (verbatim match with Homepage FAQPage JSON-LD)
    state_list_text = ", ".join(s["name"] for s in sorted(states, key=lambda x: x["name"])) or "participating U.S. states"
    home_faqs = [
        (
            "What government and auction land listings does Landosaur track?",
            "Landosaur maps %s active public-agency land offerings across %d U.S. %s (%s) from %d official government agencies as of %s—including rural state trust acreage, county tax-forfeited auction parcels, state redevelopment proposals, and municipal land-bank lots. Filter by state, price, acreage, or map area, inspect GIS outlines and FEMA flood overlays, compare county USDA/FHFA benchmarks, and open each agency's official listing directly." % (
                "{:,}".format(active_count), len(states), "state" if len(states) == 1 else "states",
                state_list_text, len(agencies), updated,
            ),
        ),
        (
            "How does Landosaur differ from LandWatch, LandSearch, Land.com, and Zillow Land?",
            "Commercial land portals such as LandWatch, LandSearch, Land.com, and Zillow Land primarily aggregate paid broker, MLS, and seller classifieds routed through agent lead forms. Landosaur reads official public-agency inventories (tax-sale auctions, state trust land, and municipal land banks) directly across all 50 states alongside free direct owner/agent listings, links every public parcel straight to its source agency portal, includes a free 9-agency Federal Parcel X-Ray (USGS LiDAR, FEMA flood/hazard, wetlands, USDA soils, roads, public lands, NASA solar) and 50-state USDA/FHFA land price benchmarks, and provides open CSV/JSON downloads and a public search API.",
        ),
        (
            "Does Landosaur sell, broker, or take commissions on government land?",
            "No. Landosaur is an independent public reference map, not an offer to sell and not a broker. Every listing links directly to the government agency's official page, where buyers confirm terms, liens, redemption rules, and bid deadlines directly with the agency.",
        ),
        (
            "How much does public-agency land cost per acre across Landosaur's active catalog?",
            (
                "Across the %s active listings that publish both a price or minimum bid and acreage (%s snapshot), the median is %s per acre (mean %s per acre), "
                "while the median published price or opening bid across all %s priced listings is %s. Exact per-state and per-agency medians are published on Landosaur's Research page, and 50-state USDA benchmarks are on the Land Prices hub."
            ) % (
                "{:,}".format(len(with_both)), updated, fmt_money_exact(median_ppa), fmt_money_exact(mean_ppa),
                "{:,}".format(len(with_price)), fmt_money_exact(median_price),
            ) if with_both else (
                "Landosaur shows only the exact price or minimum bid published by each government agency and never fabricates estimates when an agency leaves price blank."
            ),
        ),
        (
            "How often are official agency land inventories updated?",
            "The most recent source snapshot was checked on %s. Failed or partial reads never wipe existing listings; "
            "parcels leave the active map only after two consecutive complete agency reads no longer list them, or if a source goes %d days without a verified read." % (
                updated, config.CURRENT_DAYS,
            ),
        ),
        (
            "Why do some listings show no price or no acreage on the map?",
            "Landosaur publishes only the facts stated by the official agency. Municipal land banks such as St. Louis LRA, Kansas City Land Bank, and Detroit Land Bank accept buyer applications without posting asking prices in open-data feeds (%s active listings), "
            "and some tax-forfeited subdivision lots omit acreage; missing fields are shown honestly rather than guessed." % "{:,}".format(kind_counts.get("none", 0)),
        ),
    ]

    return {
        "updated": updated,
        "active_count": active_count,
        "total_tracked": total_tracked,
        "state_count": len(states),
        "county_count": county_total,
        "agency_count": len(agencies),
        "acres_reported_count": len(with_acres),
        "acres_missing_count": active_count - len(with_acres),
        "total_acres": total_acres,
        "median_acres": median_acres,
        "mean_acres": mean_acres,
        "priced_count": len(with_price),
        "unpriced_count": active_count - len(with_price),
        "median_price": median_price,
        "mean_price": mean_price,
        "both_count": len(with_both),
        "median_ppa": median_ppa,
        "mean_ppa": mean_ppa,
        "price_kinds": {
            "none": {"count": kind_counts.get("none", 0), "pct": fmt_pct(kind_counts.get("none", 0), active_count)},
            "min_bid": {"count": kind_counts.get("min_bid", 0), "pct": fmt_pct(kind_counts.get("min_bid", 0), active_count)},
            "cash": {"count": kind_counts.get("cash", 0), "pct": fmt_pct(kind_counts.get("cash", 0), active_count)},
        },
        "fixed_price": {
            "count": len(fixed_rows),
            "both_count": len(fixed_both),
            "total_acres": fixed_acres,
            "median_price": fixed_median_price,
            "median_ppa": fixed_median_ppa,
        },
        "states": states,
        "agencies": agencies,
        "top_counties": top_counties,
        "price_brackets": price_brackets,
        "acreage_brackets": acreage_brackets,
        "largest_parcel": largest_parcel,
        "lowest_priced": lowest_priced,
        "highest_priced": highest_priced,
        "findings": findings,
        "research_faqs": research_faqs,
        "home_faqs": home_faqs,
    }
