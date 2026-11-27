"""Page templates for Landosaur — Zillow-for-Land explorer, 50-state Land Price Observatory,
29 buyer research guides, interactive Valuation Workbench, and GIS parcel dossiers.

Every number on every page comes strictly from stored official agency inventories,
USDA NASS 2010-2026 datasets, or the 3,115-county US County Land Index. Zero fabricated figures.
"""
import html
import json
import os
import urllib.parse

from . import adapters, config, guides as guides_mod, market as market_mod, research
from .model import STATE_NAMES

NOTICE = ("Landosaur lists land that government agencies offer and links to each agency's own page. It is not an offer "
          "to sell, does not sell or broker land, and is not legal, tax or investment advice. Facts were read from the "
          "source on the date shown; confirm everything with the agency before you bid or buy.")
DINO = ('<svg viewBox="0 0 64 64" aria-hidden="true" class="dino"><rect x="1" y="1" width="62" height="62" rx="21" fill="#e3f6bb"/>'
        '<path d="M17 43 12 37 19 33 14 27 23 25 22 17 31 20" fill="#62a946"/><path d="M20 52V33c0-12 7-19 19-19 12 0 17 7 17 15 0 8-6 '
        '14-15 14h-6v9Z" fill="#8dcc5f" stroke="#214b32" stroke-width="2.4" stroke-linejoin="round"/><path d="M29 52V39c0-3 2-5 6-5h15c-2 '
        '6-7 9-15 9v9" fill="#f5eeba"/><circle cx="40" cy="25" r="3.3" fill="#214b32"/><circle cx="40.9" cy="24" r="1" fill="#fff"/>'
        '<circle cx="51" cy="31" r="1.4" fill="#214b32"/><path d="M40 37q5 3 9 0" fill="none" stroke="#214b32" stroke-width="2" '
        'stroke-linecap="round"/></svg>')
NICE_TOPIC = {
    "minimum_bid": "Minimum bid", "price": "Price", "acreage": "Acreage", "parcel_number": "Parcel number",
    "section_township_range": "Section, township, range", "auction_window": "Auction window", "bids": "Bids so far",
    "added_to_auction_list": "Added to the sale list", "availability": "Availability", "lot_area": "Lot area",
    "neighborhood": "Neighborhood", "ward": "Ward", "side_lot_eligible": "Side-lot program", "irregular_lot": "Irregular lot",
    "how_the_city_acquired_it": "How the city acquired it", "parcel_outline": "Parcel outline", "file_number": "Agency file number",
    "tax_parcel_id": "Tax parcel ID", "sale_program": "Sale program", "access": "Access", "agency_description_excerpt": "Agency description",
    "agency_map": "Agency map", "bid_deadline": "Bid deadline", "trust_parcel_number": "Trust parcel number", "road_access": "Road access",
    "dnr_parcel": "DNR parcel", "program": "Program", "water_access": "Water access", "remote_access": "Remote access",
    "alaska_residents_only": "Alaska residents only", "region": "Region", "case_file": "Case file",
    "zoning": "Zoning", "council_district": "Council district", "school_district": "School district",
    "property_class": "Property class", "acquired_date": "Acquired date", "proposal_deadline": "Proposal deadline",
    "agency_site_id": "Agency site ID", "city_valuation": "City open-data valuation", "buildable_lot": "Agency buildable flag",
    "legal_description": "Legal description", "tax_year": "Tax roll year", "auction_item": "Auction item", "use_code": "Assessor use code",
}


def esc(t):
    return html.escape("" if t is None else str(t), quote=True)


def money(v, dash="None published"):
    if v is None:
        return dash
    return "$" + ("{:,.2f}".format(v) if abs(v - round(v)) >= 0.005 else "{:,}".format(int(round(v))))


def acres_text(a):
    if not a:
        return "Not stated"
    return ("%.2f" % a).rstrip("0").rstrip(".") + (" acre" if abs(a - 1) < 1e-9 else " acres")


def price_line(r):
    if r["price"] is None:
        return "No price published"
    return "%s %s" % (adapters.PRICE_KIND.get(r["price_kind"], "Price"), money(r["price"]))


def date_text(iso):
    return (iso or "")[:10]


def listing_is_indexable(r):
    """Focus search crawl budget on priced or deadline-bearing active parcels rather than unpriced municipal lot grids."""
    return bool(r.get("available") and (r.get("price") is not None or r.get("deadline")))


class Site(object):
    def __init__(self, catalog):
        self.cat = catalog
        self.base = config.base_path()
        self.benchmarks = research.compute_benchmarks(catalog)
        self.market = market_mod.MarketData(catalog)
        self.all_states = self.market.all_states()
        self.guides = guides_mod.load_guides(catalog.data_dir, self.base)
        portals_path = os.path.join(catalog.data_dir, "market", "state-land-portals.json")
        if os.path.exists(portals_path):
            with open(portals_path, encoding="utf-8") as fh:
                self.state_portals = json.load(fh)
        else:
            self.state_portals = {}

    def u(self, path):
        return self.base + path

    def absu(self, path):
        return config.BASE_URL + path

    def org_node(self):
        return {
            "@type": "Organization",
            "@id": self.absu("/#organization"),
            "name": "Landosaur",
            "url": self.absu("/"),
            "logo": self.absu("/assets/favicon.svg"),
            "description": config.TAGLINE,
        }

    def layout(self, title, description, path, body, indexable=True, jsonld=None, og="default", scripts=(), wide=False):
        index = indexable and config.INDEXABLE
        head = [
            '<meta charset="utf-8">', '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>%s</title>" % esc(title), '<meta name="description" content="%s">' % esc(description),
            '<link rel="canonical" href="%s">' % esc(self.absu(path)),
            '<meta name="robots" content="%s">' % ("index, follow, max-image-preview:large" if index else "noindex, follow"),
            '<meta property="og:type" content="website">', '<meta property="og:site_name" content="Landosaur">',
            '<meta property="og:title" content="%s">' % esc(title), '<meta property="og:description" content="%s">' % esc(description),
            '<meta property="og:url" content="%s">' % esc(self.absu(path)),
            '<meta property="og:image" content="%s">' % esc(self.absu("/og/%s.png" % og)),
            '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">',
            '<meta name="twitter:card" content="summary_large_image">',
            '<link rel="icon" href="%s" type="image/svg+xml">' % self.u("/assets/favicon.svg"),
            '<link rel="preconnect" href="https://fonts.googleapis.com">',
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=optional">',
            '<link rel="stylesheet" href="%s">' % self.u("/assets/style.css"),
            '<script>try{var t=localStorage.getItem("landosaur_theme");if(t==="dark"||t==="light")document.documentElement.setAttribute("data-theme",t);}catch(e){}</script>',
            '<link rel="alternate" type="application/atom+xml" title="New government land listings" href="%s">' % self.u("/feeds/new.xml"),
            '<script src="https://rsio.org/vital.js" defer></script>',
        ]
        if any(k in s for s in scripts for k in ("map", "listing", "xray", "list", "direct", "services")):
            head.append('<link rel="stylesheet" href="%s">' % self.u("/assets/vendor/leaflet.css"))
            head.append('<link rel="stylesheet" href="%s">' % self.u("/assets/vendor/MarkerCluster.css"))
            head.append('<link rel="stylesheet" href="%s">' % self.u("/assets/vendor/MarkerCluster.Default.css"))
        for block in jsonld or []:
            head.append('<script type="application/ld+json">%s</script>' % json.dumps(block, separators=(",", ":")).replace("</", "<\\/"))
        nav_items = (
            ("/", "Map", False, ""),
            ("/services/", "Land Agent", True, "offer_clicked"),
            ("/xray/", "Parcel X-Ray", True, "tool_used"),
            ("/list/", "List Land", True, "tool_used"),
            ("/land-atlas/", "Land Atlas", False, ""),
            ("/land-for-sale/", "Land for Sale", False, ""),
            ("/land-prices/", "Land Prices", False, ""),
            ("/analyze/", "Analyzer", False, "tool_used"),
            ("/research/", "Research", False, ""),
        )
        nav = "".join(
            '<a href="%s"%s%s%s>%s</a>' % (
                self.u(p),
                ' class="nav-cta"' if is_cta else "",
                ' aria-current="page"' if path == p or (p != "/" and path.startswith(p)) else "",
                (' data-vital-event="%s"' % ev) if ev else "",
                t,
            )
            for p, t, is_cta, ev in nav_items
        )
        extra = ""
        if config.SUPPORT_URL:
            extra += ' · <a href="%s" rel="noopener sponsored">Support Landosaur</a>' % esc(config.SUPPORT_URL)
        foot = (
            '<footer><div class="wrap"><p class="notice">%s</p>'
            '<p>Official agencies tracked (%d): %s. <a href="%s">How sources are read</a>.</p>'
            '<p>County land values across 3,115 U.S. counties: <a href="%s/" rel="nofollow noopener noreferrer">US County Land Index</a> · '
            '<a href="%s">50-State Land Data Atlas &amp; Charts</a> · <a href="%s">Land Agent Services ($20)</a> · <a href="%s">Free U.S. Parcel X-Ray</a>.</p>'
            '<p><a href="%s">Land Agent ($20)</a> · <a href="%s">Land Atlas &amp; Charts</a> · <a href="%s">Land for Sale</a> · <a href="%s">List Land (Human / AI Agent)</a> · <a href="%s">Direct Marketplace</a> · <a href="%s">Parcel X-Ray</a> · <a href="%s">Land Prices</a> · <a href="%s">Analyzer</a> · '
            '<a href="%s">Research &amp; Guides</a> · <a href="%s">Closing Soon</a> · <a href="%s">Sources</a> · <a href="%s">New Listings</a> · <a href="%s">Data Downloads</a> · '
            '<a href="%s">About</a> · <a href="%s" rel="noopener">Source Code</a> · '
            '<a href="%s" rel="noopener">Report a Problem</a>%s</p></div></footer>'
        ) % (
            esc(NOTICE), len(adapters.SOURCES), ", ".join(esc(s["agency"]) for s in adapters.SOURCES), self.u("/sources/"),
            esc(config.LAND_INDEX_URL), self.u("/land-atlas/"), self.u("/services/"), self.u("/xray/"),
            self.u("/services/"), self.u("/land-atlas/"), self.u("/land-for-sale/"), self.u("/list/"), self.u("/direct/"), self.u("/xray/"), self.u("/land-prices/"), self.u("/analyze/"),
            self.u("/research/"), self.u("/closing-soon/"), self.u("/sources/"), self.u("/new/"), self.u("/data/"),
            self.u("/about/"), esc(config.REPO_URL), esc(config.REPO_URL + "/issues"), extra,
        )
        tail = "".join('<script src="%s" defer></script>' % self.u("/assets/" + s) for s in (("theme.js",) + tuple(scripts)))
        if config.GOATCOUNTER:
            tail += '<script data-goatcounter="%s" async src="https://gc.zgo.at/count.js"></script>' % esc(config.GOATCOUNTER)
        return (
            '<!doctype html><html lang="en"><head>%s</head><body data-base="%s"><a class="skip" href="#main">Skip to content</a>'
            '<header><div class="wrap"><a class="brand" href="%s">%s<span>Landosaur</span></a>'
            '<nav aria-label="Main">%s<button type="button" id="theme-toggle" class="theme-toggle" aria-label="Toggle light or dark theme">☾ Theme</button></nav></div></header>'
            '<main id="main" class="wrap%s">%s</main>%s%s</body></html>'
        ) % ("".join(head), esc(self.base), self.u("/"), DINO, nav, " wide" if wide else "", body, foot, tail)

    def crumbs(self, trail):
        items = [("Map", "/")] + trail
        h = '<nav class="crumbs" aria-label="Breadcrumb">%s</nav>' % " › ".join(
            ('<a href="%s">%s</a>' % (self.u(p), esc(n))) if i < len(items) - 1 else "<span>%s</span>" % esc(n)
            for i, (n, p) in enumerate(items))
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": self.absu(p)} for i, (n, p) in enumerate(items)]}
        return h, ld

    def badge(self, r):
        cls = "ok" if r["available"] else "off"
        if r["status"] in ("auction_open", "auction_terms", "proposal_open") and r["available"]:
            cls = "auction"
        label = r["status_label"] if r["fresh"] else "Not re-checked recently"
        return '<span class="badge %s">%s</span>' % (cls if r["fresh"] else "off", esc(label))

    def rows(self, listings, show_state=False, show_ppa=False):
        out = []
        for r in listings:
            where = r["county_label"] + (", " + r["state"] if show_state else "")
            ppa_td = ""
            if show_ppa:
                ppa = (r["price"] / r["acres"]) if (r.get("price") and r.get("acres")) else None
                ppa_td = '<td class="n" data-label="$/acre" data-v="%s">%s</td>' % (
                    "%.2f" % ppa if ppa is not None else "",
                    esc(money(ppa)) + "/ac" if ppa is not None else "–",
                )
            out.append(
                '<tr><th scope="row"><a href="%s">%s</a><span class="sub">%s</span></th><td data-label="Status">%s</td>'
                '<td class="n" data-label="Price" data-v="%s">%s</td><td class="n" data-label="Acres" data-v="%s">%s</td>'
                '%s<td data-label="Deadline">%s</td></tr>' % (
                    self.u(self.cat.listing_path(r)), esc(r["title"]), esc(where), self.badge(r),
                    r["price"] if r["price"] is not None else "", esc(price_line(r)) if r["price"] is not None else "–",
                    r["acres"] or "", esc(acres_text(r["acres"])) if r["acres"] else "–",
                    ppa_td, esc(date_text(r.get("deadline"))) or "–",
                )
            )
        ppa_th = '<th scope="col" class="n">$/acre</th>' if show_ppa else ""
        return (
            '<div class="scroll"><table class="data sortable listings"><thead><tr>'
            '<th scope="col">Listing</th><th scope="col">Status</th>'
            '<th scope="col" class="n">Price or min bid</th><th scope="col" class="n">Acres</th>'
            '%s<th scope="col">Deadline</th></tr></thead><tbody>%s</tbody></table></div>' % (ppa_th, "".join(out))
        )

    def updated(self):
        return (self.cat.status.get("checked") or "")[:10]

    def faq_block(self, faqs, heading="Frequently asked questions", intro=None, section_id="faq"):
        items = "".join(
            '<details class="faq-item"><summary>%s</summary><p>%s</p></details>' % (esc(q), esc(a))
            for q, a in faqs
        )
        intro_html = '<p class="small">%s</p>' % intro if intro else ""
        return '<section id="%s"><h2>%s</h2>%s<div class="faq-list">%s</div></section>' % (
            esc(section_id), esc(heading), intro_html, items)

    def faq_jsonld(self, faqs, fragment="/#faq"):
        return {
            "@type": "FAQPage",
            "@id": self.absu(fragment),
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in faqs
            ],
        }

    def map_block(self, scope, title="Interactive Land Map"):
        states = sorted(self.cat.states.values(), key=lambda s: s["name"])
        opts = "".join(
            '<option value="%s"%s>%s</option>' % (s["code"], " selected" if scope == s["code"] else "", esc(s["name"]))
            for s in states
        )
        scoped = [r for r in self.cat.current() if scope == "all" or r["state"] == scope]
        cnt_all = len(scoped)
        cnt_cash = sum(1 for r in scoped if r["price_kind"] == "cash")
        cnt_auc = sum(1 for r in scoped if r["price_kind"] == "min_bid" or r["status"] in ("auction_open", "auction_terms"))
        cnt_none = sum(1 for r in scoped if r["price_kind"] == "none" and r["status"] not in ("auction_open", "auction_terms"))
        return (
            '<section class="mapzone" aria-label="%s">'
            '<div class="mode-switcher" role="group" aria-label="Filter by deal type">'
            '<button type="button" class="mode-btn active" data-deal-mode="" data-vital-event="tool_used">All Land (%s)</button>'
            '<button type="button" class="mode-btn" data-deal-mode="cash" data-vital-event="tool_used">Buy It Now (%s)</button>'
            '<button type="button" class="mode-btn" data-deal-mode="min_bid" data-vital-event="tool_used">Auction / Bid (%s)</button>'
            '<button type="button" class="mode-btn" data-deal-mode="none" data-vital-event="tool_used">Land Bank / Offer (%s)</button>'
            '<button type="button" class="mode-btn" data-deal-mode="direct" data-vital-event="tool_used">Direct Owner / Agent (0)</button>'
            '<a class="mode-btn" href="%s" data-vital-event="tool_used" style="margin-left:auto;border-color:var(--forest);color:var(--forest)">+ List Land Free</a>'
            '</div>'
            '<form class="filters" id="filters" onsubmit="return false">'
            '<label>State<select name="state"><option value="">All tracked states</option>%s</select></label>'
            '<label>Deal mode<select name="kind"><option value="">Any deal type</option><option value="cash">Buy It Now (fixed price)</option>'
            '<option value="min_bid">Auction / min bid</option><option value="none">Land bank / offer</option><option value="direct">Direct Owner / Agent</option></select></label>'
            '<label>Max price<input name="max" type="number" min="0" step="100" inputmode="numeric" placeholder="Any"></label>'
            '<label>Min acres<input name="acres" type="number" min="0" step="0.1" inputmode="decimal" placeholder="Any"></label>'
            '<label>Sort<select name="sort"><option value="default">Recommended</option><option value="deadline">Closing soonest</option>'
            '<option value="ppa_asc">Lowest $/acre</option><option value="price_asc">Price: low to high</option>'
            '<option value="price_desc">Price: high to low</option><option value="acres_desc">Largest acreage</option></select></label>'
            '<label class="grow">Search<input name="q" type="search" placeholder="County, city, address, parcel ID"></label>'
            '<div class="preset-bar" aria-label="Quick filters" style="flex-basis:100%%;margin:4px -16px -14px;border-top:1px solid var(--line);border-bottom:0">'
            '<button type="button" class="pill-btn" data-preset="all" data-vital-event="tool_used">All active</button>'
            '<button type="button" class="pill-btn" data-preset="cash" data-vital-event="tool_used">Buy It Now</button>'
            '<button type="button" class="pill-btn" data-preset="min_bid" data-vital-event="tool_used">Auction / Bid</button>'
            '<button type="button" class="pill-btn" data-preset="direct" data-vital-event="tool_used">Direct Owner / Agent</button>'
            '<button type="button" class="pill-btn" data-preset="acres5" data-vital-event="tool_used">5+ acres</button>'
            '<button type="button" class="pill-btn" data-preset="under5k" data-vital-event="tool_used">Under $5,000</button>'
            '<button type="button" class="pill-btn" data-preset="ppa" data-vital-event="tool_used">Lowest $/acre</button>'
            '<button type="button" class="pill-btn" data-preset="saved" data-vital-event="tool_used">Saved shortlist ★</button>'
            '<div class="filter-toggles">'
            '<label><input name="inview" type="checkbox"> Search map area</label>'
            '<label><input name="savedOnly" type="checkbox"> Saved only</label>'
            '<label><input name="closed" type="checkbox"> Include closed</label>'
            '</div></div></form>'
            '<div class="explorer-split">'
            '<div class="explorer-map-col"><div id="map" class="map" data-scope="%s">'
            '<noscript><p>The map needs JavaScript. Browse state directories below.</p></noscript></div>'
            '<div class="map-legend" aria-hidden="true">'
            '<span><i style="background:#1d6f42"></i>Buy It Now</span>'
            '<span><i style="background:#b5602f"></i>Auction / Bid</span>'
            '<span><i style="background:#2f7d6e"></i>Land bank / offer</span>'
            '<span><i style="background:#16a34a"></i>Direct Owner / Agent</span>'
            '</div></div>'
            '<div class="explorer-list-col"><div class="list-head"><p class="small" id="map-count" aria-live="polite"></p></div>'
            '<div id="results" class="results"></div></div>'
            '</div>'
            '<div id="compare-dock" class="compare-dock" hidden>'
            '<span>Saved: <strong data-saved-count>0</strong> · Compare: <strong data-cmp-count>0</strong>/4</span>'
            '<button type="button" data-open-compare data-vital-event="tool_used">Compare side by side</button>'
            '<button type="button" class="ghost-dk" data-export-saved data-vital-event="tool_used">Export Saved CSV</button>'
            '<button type="button" class="ghost-dk" data-clear-compare>Clear</button>'
            '</div>'
            '<div id="compare-modal" class="compare-modal" hidden role="dialog" aria-modal="true" aria-label="Compare parcels">'
            '<div class="compare-panel"><div class="compare-head"><h2>Parcel comparison</h2>'
            '<button type="button" class="button ghost sm" data-close-compare>Close</button></div>'
            '<div data-cmp-body></div></div></div>'
            '</section>'
        ) % (
            esc(title),
            "{:,}".format(cnt_all), "{:,}".format(cnt_cash), "{:,}".format(cnt_auc), "{:,}".format(cnt_none),
            self.u("/list/"), opts, esc(scope),
        )

    def platform_comparison_block(self, active_count, state_count, agency_count):
        return (
            '<section id="land-platform-comparison">'
            '<h2>How Landosaur compares to commercial land marketplaces</h2>'
            '<p class="small">Side-by-side comparison of public-record transparency, rural parcel search, due-diligence screening, fees, and direct inquiry workflows across Landosaur, LandWatch, LandSearch, Land.com, and Zillow Land.</p>'
            '<div class="scroll"><table class="data compare-matrix"><thead><tr>'
            '<th scope="col">Comparison factor</th>'
            '<th scope="col" class="col-ours">Landosaur</th>'
            '<th scope="col">LandWatch</th>'
            '<th scope="col">LandSearch</th>'
            '<th scope="col">Land.com</th>'
            '<th scope="col">Zillow Land</th>'
            '</tr></thead><tbody>'
            '<tr><th scope="row">County parcel &amp; deed source transparency</th>'
            '<td class="col-ours">Maps %s official public-agency offerings (%d agencies across %d states, checked daily) plus direct owner/agent listings; every public parcel links straight to its official agency portal with parcel APN and GIS boundary when published.</td>'
            '<td>Paid broker, agent, and owner classified listings (CoStar / Land.com network); links route to brokers rather than county/state agency portals.</td>'
            '<td>Aggregates broker/MLS, auction, and owner land listings; county assessor or public source links vary by feed.</td>'
            '<td>Paid broker, land-specialist, and auctioneer classifieds (CoStar network); primary contact is the listing brokerage.</td>'
            '<td>MLS-syndicated and FSBO lots with basic county tax-assessment history; does not index municipal land banks or state trust auctions.</td></tr>'
            '<tr><th scope="row">Rural acreage &amp; deal-mode filters</th>'
            '<td class="col-ours">Splits Buy It Now, Auction / Min Bid, Land Bank / Offer, and Direct listings; filters by state, max price, min acreage, $/acre sort, viewport bounds, saved CSV shortlist, and 4-parcel side-by-side comparison.</td>'
            '<td>Filters by state, county, price, acreage, and land category (hunting, farms, timber, residential, waterfront).</td>'
            '<td>Interactive map with acreage, price, land-use, water, and mineral filters across rural and commercial land.</td>'
            '<td>Acreage, price, and lifestyle/recreational category filters paired with a rural brokerage directory.</td>'
            '<td>Lot-size and price filters inside a residential MLS search interface; no auction vs. land-bank deal-mode split.</td></tr>'
            '<tr><th scope="row">Fee &amp; commission model</th>'
            '<td class="col-ours">Free to search, map, X-Ray, analyze, list land, and download open CSV/JSON data; optional turnkey Land Agent Concierge ($20 initiation + 10%% fee only on closed acquisition).</td>'
            '<td>Free for buyers to browse; paid advertising and broker subscription packages fund listing placement.</td>'
            '<td>Free for buyers to browse; paid seller, broker, and lead-generation plans.</td>'
            '<td>Free for buyers to browse; paid brokerage marketing and featured-listing subscriptions.</td>'
            '<td>Free for buyers to browse; funded by Premier Agent / broker advertising and lead referrals.</td></tr>'
            '<tr><th scope="row">Public-record hazard, soil &amp; ownership visibility</th>'
            '<td class="col-ours">Built-in free 9-agency Federal Parcel X-Ray (USGS LiDAR slope, FEMA flood &amp; hazard risk, USFWS wetlands, USDA soil/bedrock depth, Census roads, USGS public lands, NASA solar, 3,115-county USDA/FHFA benchmarks); excludes previous-owner PII for privacy.</td>'
            '<td>Relies on broker-entered descriptions and photos; buyers run FEMA flood, wetland, soil, and zoning checks externally.</td>'
            '<td>Listing summaries with select map overlays; buyers verify soils, wetlands, and county zoning outside the listing.</td>'
            '<td>Broker descriptions and aerial maps; no built-in 9-agency federal GIS screening workbench.</td>'
            '<td>Parcel outline and third-party flood/fire summary; limited rural soil/septic, wetland, and BLM/Forest adjacency data.</td></tr>'
            '<tr><th scope="row">Direct buyer/seller inquiry &amp; open data flow</th>'
            '<td class="col-ours">Direct link to official government bidding/application pages, on-site offers/bids for direct listings, turnkey Land Agent desk, plus open CSV/JSON downloads, Atom feeds, and <code>/api/search/</code>.</td>'
            '<td>Lead-capture contact form routed to the listing broker or seller; no open bulk CSV/JSON feed.</td>'
            '<td>Inquiry form routed to listing broker, auctioneer, or owner; no open public-agency dataset export.</td>'
            '<td>Broker inquiry form and phone lead routing; no public bulk data downloads.</td>'
            '<td>&ldquo;Contact agent&rdquo; form routed to buyer/Premier agents or listing brokers; closed MLS data terms.</td></tr>'
            '</tbody></table></div>'
            '<p class="small">Marketplace features reflect publicly documented product models as of November 2026; verify current terms directly with each platform. '
            '<a href="%s" data-vital-event="tool_used">Run a free 9-agency Parcel X-Ray →</a> · <a href="%s" data-vital-event="offer_clicked">Hire Land Agent ($20) →</a></p>'
            '</section>'
        ) % (
            "{:,}".format(active_count), agency_count, state_count,
            self.u("/xray/"), self.u("/services/"),
        )

    def how_block(self):
        return (
            '<section><h2>How Landosaur works</h2><ul class="notes">'
            '<li><strong>Official public sources + direct listings.</strong> City, county, state trust, and tax-sale feeds across %d states plus 50-state direct owner, real estate agent, and AI-agent listings. Zero scraped broker spam.</li>'
            '<li><strong>9-agency GIS Parcel X-Ray.</strong> Instant USGS 3DEP terrain profile, FEMA flood &amp; disaster risk, USFWS wetlands, USDA soil/septic depth, Census roads, USGS public-land adjacency, NASA solar/hardiness, and USDA/FHFA county benchmarks.</li>'
            '<li><strong>Clear Buy It Now vs. Auction bidding.</strong> Filter fixed-price Buy It Now parcels separately from auctions; bid or reserve direct listings on-site and link directly to official portals for government parcels.</li>'
            '<li><strong>Two-sided Agent-native API &amp; Analyzer.</strong> Search 23,500+ parcels via <code>/api/search/</code>, publish any U.S. parcel in 60 seconds via <a href="%s">/list/</a> or a single AI agent API call, and model full all-in deal economics in the <a href="%s">Land Analyzer</a>.</li>'
            '</ul><p><a href="%s">About our rules</a> · <a href="%s">All official sources</a> · <a href="%s">50-State Land Prices</a> · <a href="%s">Open Data &amp; RSS Feeds</a></p></section>'
        ) % (len(self.cat.states), self.u("/list/"), self.u("/analyze/"), self.u("/about/"), self.u("/sources/"), self.u("/land-prices/"), self.u("/data/"))

    # ------------------------------------------------------------------ home (map)
    def home(self):
        cat = self.cat
        b = self.benchmarks
        cur = cat.current()
        n_src = sum(1 for s in cat.status.get("sources", {}).values() if s.get("count"))
        states = sorted({r["state"] for r in cur})
        us_latest = self.market.latest_values("US")
        lede = (
            "Explore <strong>%s</strong> official government, tax-sale, state trust, and land-bank parcels across %d states (%s), "
            "plus <strong>50-state USDA/FHFA land price benchmarks</strong> across 3,115 counties, 29 due-diligence guides, and a full land valuation workbench."
            % ("{:,}".format(len(cur)), len(states), ", ".join(STATE_NAMES[s] for s in states) or "participating states")
        )
        state_tiles = "".join(
            '<a class="state-tile" href="%s"><strong>%s</strong><span>%s active</span><small>%d %s</small></a>' % (
                self.u(cat.state_path(st)), esc(st["name"]),
                "{:,}".format(sum(1 for r in st["listings"] if r["available"])),
                len(st["counties"]), "jurisdiction" if len(st["counties"]) == 1 else "jurisdictions",
            )
            for st in sorted(cat.states.values(), key=lambda s: s["name"])
        )
        new = cat.new()[:8]
        closing = cat.closing()[:8]
        us_fre = market_mod.usd(us_latest.get("farm_real_estate"))
        pillars = (
            '<section><h2>Everything you need to find, X-Ray, analyze, and acquire land across all 50 states</h2><div class="card-grid">'
            '<article class="info-card"><div class="eyebrow">Turnkey Acquisition · Listed &amp; Unlisted</div>'
            '<h3>Land Agent Concierge ($20 + 10%%)</h3>'
            '<p>Skip county paperwork and outreach. Pay $20 to initiate full verification, bidding or off-market landowner contact, and deed transfer for any parcel in America.</p>'
            '<a class="card-link" href="%s" data-vital-event="offer_clicked">Hire Land Agent ($20 to Start) →</a></article>'
            '<article class="info-card"><div class="eyebrow">50-State Interactive Data &amp; Charts</div>'
            '<h3>U.S. Land Data Atlas (2010–%d)</h3>'
            '<p>Explore our interactive 50-state cartogram, multi-state USDA growth charts (%s/ac U.S. avg), live inventory supply breakdowns, and searchable 3,115-county table.</p>'
            '<a class="card-link" href="%s" data-vital-event="tool_used">Open Land Data Atlas &amp; Charts →</a></article>'
            '<article class="info-card"><div class="eyebrow">All 50 States · 9 Live Federal APIs</div>'
            '<h3>Free U.S. Parcel X-Ray &amp; Deal Analyzer</h3>'
            '<p>Drop a pin anywhere for USGS LiDAR terrain profile, FEMA flood &amp; wildfire risk, wetlands, soil/bedrock, Census roads, public lands, solar, and full ROI modeling.</p>'
            '<a class="card-link" href="%s" data-vital-event="tool_used">Open Parcel X-Ray →</a> · <a class="card-link" href="%s" data-vital-event="tool_used">Deal Analyzer →</a></article>'
            '</div></section>'
        ) % (
            self.u("/services/"), self.market.latest_year, esc(us_fre),
            self.u("/land-atlas/"), self.u("/xray/"), self.u("/analyze/"),
        )
        body = [
            '<section class="hero-shell"><div class="hero"><div class="hero-left">'
            '<img src="%s" alt="" width="76" height="76" class="mascot"><div>'
            '<div class="eyebrow">All 50 States Live · Open Land Database, Data Atlas &amp; Land Agent</div>'
            '<h1>Find, X-Ray, and acquire land in all 50 states</h1>'
            '<p class="lede">%s</p></div></div>'
            '<div class="hero-cta-group">'
            '<a class="button" href="%s" data-vital-event="offer_clicked">Hire Land Agent ($20 · Listed or Unlisted) →</a>'
            '<a class="button ghost" href="%s" data-vital-event="tool_used">50-State Data Atlas &amp; Charts</a>'
            '<a class="button ghost" href="%s" data-vital-event="tool_used">List Land Free</a>'
            '</div></div>'
            '<div class="hero-stats">'
            '<span class="stat-pill"><strong>%s</strong> active parcels</span>'
            '<span class="stat-pill"><strong>%d/50</strong> U.S. states live</span>'
            '<span class="stat-pill"><strong>%d</strong> official agencies</span>'
            '<span class="stat-pill"><strong>3,115</strong> county benchmarks</span>'
            '<span class="stat-pill"><strong>9</strong> live federal X-Ray APIs</span>'
            '<span class="stat-pill">Updated <strong>%s</strong></span>'
            '</div></section>' % (
                self.u("/assets/mascot.png"), lede, self.u("/services/"), self.u("/land-atlas/"), self.u("/list/"),
                "{:,}".format(len(cur)), len(states), n_src, esc(self.updated() or "daily"),
            ),
            self.map_block("all"),
            '<section><h2>Browse live official inventory by state</h2><div class="state-grid">%s</div>'
            '<p style="margin-top:12px"><a href="%s" data-vital-event="tool_used"><strong>View all 50 states in the Land for Sale Directory →</strong></a></p></section>' % (
                state_tiles, self.u("/land-for-sale/"),
            ),
            pillars,
        ]
        if closing:
            body.append('<section><h2>Auctions &amp; proposals closing in the next %d days</h2>%s<p><a href="%s">View all closing soon →</a></p></section>' % (
                config.CLOSING_DAYS, self.rows(closing, True, True), self.u("/closing-soon/")))
        if new:
            body.append('<section><h2>New this fortnight</h2>%s<p><a href="%s">All new listings →</a> · <a href="%s">Atom feed</a></p></section>' % (
                self.rows(new, True), self.u("/new/"), self.u("/feeds/new.xml")))
        body.append(self.platform_comparison_block(len(cur), len(states), n_src))
        body.append(self.how_block())
        body.append(self.faq_block(
            b["home_faqs"],
            heading="Frequently asked questions",
            intro='Computed from the %s official agency snapshot. Explore state-by-state benchmarks on the <a href="%s">Research</a> and <a href="%s">50-State Land Prices</a> hubs.' % (
                esc(b["updated"]), self.u("/research/"), self.u("/land-prices/")),
        ))
        desc = (
            "Search %s official government, tax-sale, state trust, and land-bank parcels across %s on one interactive map, "
            "plus 50-state USDA/FHFA land prices per acre, GIS flood & aerial layers, 29 buyer guides, and a land valuation workbench."
        ) % ("{:,}".format(len(cur)), ", ".join(STATE_NAMES[s] for s in states) or "participating states")
        ld = [{
            "@context": "https://schema.org",
            "@graph": [
                self.org_node(),
                {
                    "@type": "WebSite",
                    "@id": self.absu("/#website"),
                    "name": "Landosaur",
                    "url": self.absu("/"),
                    "description": desc,
                    "publisher": {"@id": self.absu("/#organization")},
                },
                {
                    "@type": "BreadcrumbList",
                    "@id": self.absu("/#breadcrumb"),
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": self.absu("/")},
                    ],
                },
                {
                    "@type": "WebApplication",
                    "@id": self.absu("/#webapp"),
                    "name": "Landosaur Land Map, GIS Parcel X-Ray & Valuation Workbench",
                    "applicationCategory": "RealEstateApplication",
                    "operatingSystem": "Web",
                    "browserRequirements": "Requires JavaScript for interactive map and GIS X-Ray",
                    "url": self.absu("/"),
                    "description": desc,
                    "isAccessibleForFree": True,
                    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                    "publisher": {"@id": self.absu("/#organization")},
                    "featureList": [
                        "Split-screen interactive map with Buy It Now, Auction/Min Bid, Land Bank, and Direct deal-mode filters plus 4-parcel side-by-side comparison",
                        "Free 9-agency Federal Parcel X-Ray (USGS 3DEP LiDAR, FEMA NFHL flood & hazard risk, USFWS wetlands, USDA SSURGO soils, Census roads, PAD-US public lands, NASA solar)",
                        "50-state USDA NASS 2010-2026 land price observatory and 3,115 county USDA/FHFA land value benchmarks",
                        "Deterministic land deal, loan/balloon, grid vs. off-grid electricity, comparable sales, and residual development workbench",
                        "Daily verified official public-agency feeds with free CSV, JSON, and Atom XML downloads",
                    ],
                },
                {
                    "@type": "SoftwareApplication",
                    "@id": self.absu("/#software"),
                    "name": "Landosaur Land Map, GIS Parcel Dossier & Valuation Workbench",
                    "applicationCategory": "ReferenceApplication",
                    "operatingSystem": "Web",
                    "url": self.absu("/"),
                    "description": desc,
                    "isAccessibleForFree": True,
                    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                    "publisher": {"@id": self.absu("/#organization")},
                },
                {
                    "@type": "Dataset",
                    "@id": self.absu("/#dataset"),
                    "name": "Landosaur Official Government & Auction Land Catalog",
                    "description": desc,
                    "url": self.absu("/data/"),
                    "isAccessibleForFree": True,
                    "creator": {"@id": self.absu("/#organization")},
                    "distribution": [
                        {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": self.absu("/data/listings.csv")},
                        {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": self.absu("/data/map.json")},
                    ],
                },
                self.faq_jsonld(b["home_faqs"], "/#faq"),
            ],
        }]
        return self.layout(
            "Land for Sale Map, 50-State Land Prices & Parcel Analyzer | Landosaur",
            desc, "/", "".join(body), indexable=True, jsonld=ld,
            scripts=["vendor/leaflet.js", "vendor/leaflet.markercluster.js", "map.js", "tables.js"], wide=True,
        )

    # ------------------------------------------------------------------ /xray/ Universal 50-State Parcel X-Ray
    def xray_page(self):
        crumbs, crumb_ld = self.crumbs([("Parcel X-Ray", "/xray/")])
        faqs = [
            ("What does the Free U.S. Parcel X-Ray check?",
             "For any coordinates in all 50 U.S. states, Landosaur queries 9 official public data services live: USGS 3DEP 1m/10m LiDAR (9-point cross-section elevation profile, relief, slope % and aspect), FEMA NFHL (exact flood zone, 100-year SFHA status, BFE, and FIRM panel), FEMA National Risk Index (county Wildfire, Hurricane, Tornado, Drought, and Earthquake risk ratings), USFWS National Wetlands Inventory (wetlands within 100 meters), USDA NRCS SSURGO Soil Survey (soil map unit, prime farmland class, drainage class, hydrologic group, water table depth, and bedrock depth), U.S. Census TIGERweb Roads (nearest mapped public road & highway distances), USGS PAD-US Public Lands (National Forests, BLM land, and parks within 1 km), NASA POWER Climatology (peak sun hours, temperatures, rainfall, and USDA Plant Hardiness Zone), and FCC Census County FIPS joined to our 3,115-county USDA/FHFA Land Index."),
            ("Does Parcel X-Ray replace a survey, perc test, or title search?",
             "No. Automated federal GIS layers are a fast pre-offer screening layer so you can spot floodplains, wetlands, steep slopes, shallow bedrock, or arid off-grid constraints before spending thousands on inspections. Always obtain a licensed boundary survey, county health perc test, recorded access verification, and title insurance before closing."),
            ("Can I run Parcel X-Ray on land listed on other websites?",
             "Yes. Paste any U.S. street address, town and state, ZIP code, or GPS coordinates (latitude, longitude), or click anywhere on the interactive USGS Satellite / Topo / FEMA map. You can copy a permanent share link or print a clean Field Visit PDF packet."),
        ]
        body = [
            crumbs,
            '<div class="eyebrow">All 50 U.S. States · 9 Live Federal APIs · KML/GPX Export · Free Forever</div>',
            '<h1>Free U.S. Parcel X-Ray: Flood, Soil, Roads, Public Land &amp; Slope</h1>',
            '<p class="lede">Click anywhere on the satellite map—or enter any U.S. address, town, or GPS coordinates—to screen raw land across <strong>USGS 3DEP LiDAR (with 656-ft terrain cross-section)</strong>, <strong>FEMA Flood &amp; Wildfire/Hazard Risk</strong>, <strong>USFWS Wetlands</strong>, <strong>USDA SSURGO Soil/Bedrock</strong>, <strong>Census Road Proximity</strong>, <strong>USGS Public Lands</strong>, <strong>NASA Solar &amp; Growing Zone</strong>, and <strong>3,115-county land values</strong>.</p>',
            '<div id="xray-app">',
            '<form id="xray-search-form" class="xray-search-bar" aria-label="Search any U.S. location">'
            '<input id="xray-q" type="search" placeholder="Enter address, town &amp; state, ZIP, or lat, lon (e.g. Sedona, AZ or 35.42, -92.45)" aria-label="U.S. address, town, or coordinates">'
            '<button type="submit" class="button" data-vital-event="tool_used">Run Federal X-Ray</button>'
            '</form>',
            '<div class="preset-bar" style="border-radius:12px;border:1px solid var(--line);margin-bottom:14px">'
            '<span class="small" style="font-weight:650;margin-right:4px">Try a real parcel:</span>'
            '<button type="button" class="pill-btn" data-xray-preset="35.42,-92.45" data-xray-label="Van Buren County, AR" data-vital-event="tool_used">Ozark Rural Tract (AR)</button>'
            '<button type="button" class="pill-btn" data-xray-preset="34.4160,-118.4352" data-xray-label="Santa Clarita, CA" data-vital-event="tool_used">LA County Auction Lot (CA)</button>'
            '<button type="button" class="pill-btn" data-xray-preset="34.8689,-111.7614" data-xray-label="Sedona, AZ" data-vital-event="tool_used">High Desert Parcel (AZ)</button>'
            '<button type="button" class="pill-btn" data-xray-preset="41.6639,-83.5379" data-xray-label="Toledo, OH" data-vital-event="tool_used">Toledo Land Bank Lot (OH)</button>'
            '</div>',
            '<div id="xray-map" class="map xray-tall" aria-label="Click anywhere on the U.S. map to run Parcel X-Ray">'
            '<noscript><p>Enable JavaScript to use the interactive Parcel X-Ray map.</p></noscript></div>',
            '<p id="xray-status" class="small" aria-live="polite" style="margin-top:10px;font-weight:600">Click anywhere on the map above or search a U.S. location to run an instant 6-agency Federal Parcel X-Ray.</p>',
            '<div id="xray-actions" class="btn-row" hidden></div>',
            '<section class="xray-section" style="margin-top:16px">'
            '<div class="xray-header"><div><div class="eyebrow">Live Federal GIS Screening</div>'
            '<h2>Parcel Physical Intelligence &amp; Land Potential</h2></div></div>'
            '<div id="xray-results"><p class="small">Select a point on the map or click one of the example locations above to populate live USGS elevation/slope, FEMA flood zone, USFWS wetlands, USDA soil/septic depth, NASA solar/rainfall, and county value benchmarks.</p></div>'
            '</section>',
            '<section class="print-checklist"><h2>On-Site Field Visit Verification Checklist</h2><ul>'
            '<li>&#9744; Verified recorded legal road access &amp; physical driveway grade</li>'
            '<li>&#9744; Located boundary corners / checked encroachment or neighbor fences</li>'
            '<li>&#9744; Measured nearest overhead power pole &amp; transformer distance</li>'
            '<li>&#9744; Checked surface drainage, standing water &amp; seasonal creek channels</li>'
            '<li>&#9744; Confirmed zoning, setbacks &amp; minimum dwelling rules with county</li>'
            '<li>&#9744; Confirmed clean title, back taxes, liens &amp; septic perc requirements</li>'
            '</ul></section>',
            '</div>',
            self.faq_block(faqs, heading="How the Federal Parcel X-Ray works", section_id="xray-faq"),
        ]
        desc = "Free U.S. Parcel X-Ray for all 50 states: check USGS LiDAR elevation & slope %, FEMA NFHL flood zone, USFWS wetlands, USDA SSURGO soil/septic/bedrock depth, NASA peak sun hours, and county land value per acre."
        ld = [{"@context": "https://schema.org", "@graph": [
            self.org_node(),
            {k: v for k, v in crumb_ld.items() if k != "@context"},
            {
                "@type": "SoftwareApplication", "@id": self.absu("/xray/#app"),
                "name": "Landosaur Free U.S. Parcel X-Ray",
                "applicationCategory": "ReferenceApplication", "operatingSystem": "Web",
                "url": self.absu("/xray/"), "description": desc, "isAccessibleForFree": True,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "publisher": {"@id": self.absu("/#organization")},
            },
            self.faq_jsonld(faqs, "/xray/#faq"),
        ]}]
        return self.layout(
            "Free U.S. Parcel X-Ray — Flood, Soil, Slope, Wetlands & Solar Checker | Landosaur",
            desc, "/xray/", "".join(body), indexable=True, jsonld=ld,
            scripts=["vendor/leaflet.js", "xray.js"], wide=True,
        )

    # ------------------------------------------------------------------ /list/ Agent-First Land Listing Flow
    def list_page(self):
        crumbs, crumb_ld = self.crumbs([("List Land", "/list/")])
        agent_prompt = (
            "List my land on Landosaur by sending a POST request to https://landosaur.com/api/listings/ "
            "(read https://landosaur.com/.well-known/landosaur-agent.json for the schema).\n"
            "Details:\n"
            "- Location / GPS: [insert address, town & state, or lat, lon]\n"
            "- Acreage: [insert acres]\n"
            "- Sale Mode: [buy_now OR auction]\n"
            "- Price / Starting Bid: $[insert USD]\n"
            "- Optional Buy It Now or Auction End Date: [insert or omit]\n"
            "- Contact Name & Email: [insert name and email]\n"
            "- Seller Type: [owner OR agent + brokerage]\n"
            "- Optional Stripe/Escrow Checkout URL: [insert https://... or omit]\n"
            "- Notes (access, utilities, seller financing): [insert brief facts]\n"
            "Return the live Landosaur listing URL, auto-enriched Federal Parcel X-Ray summary, and my Seller Edit Token."
        )
        curl_snippet = (
            "curl -X POST https://landosaur.com/api/listings/ \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -d '{\n"
            '    "location": "Van Buren County, AR",\n'
            '    "lat": 35.42, "lon": -92.45,\n'
            '    "acres": 10,\n'
            '    "sale_mode": "auction",\n'
            '    "starting_bid": 15000,\n'
            '    "buy_now_price": 29500,\n'
            '    "seller_type": "agent",\n'
            '    "contact_name": "Alex Rivera",\n'
            '    "brokerage": "Ozark Land Realty",\n'
            '    "contact_email": "alex@example.com",\n'
            '    "road_access": "Gravel county road frontage",\n'
            '    "submitted_by_agent": "claude"\n'
            "  }'"
        )
        body = [
            crumbs,
            '<div class="eyebrow">All 50 States · Free · Zero Accounts · Human or AI Agent</div>',
            '<h1>List Your Land in 60 Seconds—or With Just Your AI Agent</h1>',
            '<p class="lede">The easiest place on earth for landowners, real estate agents, and AI agents (Claude, ChatGPT, Codex, Gemini, Antigravity) to publish <strong>Buy It Now</strong> or <strong>Live Auction</strong> land across all 50 states. Drop one pin and Landosaur auto-fills county, USGS LiDAR slope, FEMA flood &amp; wildfire risk, USDA soil/bedrock, Census road distance, USGS public lands, and county $/acre benchmarks automatically.</p>',
            '<div id="list-app">',

            # AI Agent 1-Prompt Publishing Panel
            '<section class="xray-section" id="agent-publish" style="margin-top:16px">'
            '<div class="xray-header"><div><div class="eyebrow">Option 1 · Machine-First Publishing</div>'
            '<h2>Tell Your AI Agent to List It For You</h2></div>'
            '<a class="button ghost sm" href="%s">Open Agent JSON Schema ↗</a></div>'
            '<p class="small">Paste this prompt into Claude, ChatGPT, Codex, Gemini, or Antigravity—your agent publishes directly to <code>POST https://landosaur.com/api/listings/</code> with zero form-filling and returns your live Buy It Now / Auction URL + Seller Edit Token.</p>'
            '<pre id="agent-prompt-text" class="code-box">%s</pre>'
            '<div class="btn-row">'
            '<button type="button" class="button sm" data-copy-target="agent-prompt-text">Copy AI Agent Prompt</button>'
            '<button type="button" class="button ghost sm" data-copy-target="agent-curl-text">Copy cURL Example</button>'
            '<a class="button ghost sm" href="%s">View Live Direct Marketplace →</a>'
            '</div>'
            '<details class="faq-item"><summary>Developer / Broker Agent cURL Payload</summary>'
            '<div style="padding:0 16px 14px"><pre id="agent-curl-text" class="code-box">%s</pre></div></details>'
            '</section>' % (self.u("/.well-known/landosaur-agent.json"), esc(agent_prompt), self.u("/direct/"), esc(curl_snippet)),

            # Human / Real Estate Agent 60-Second Drop-a-Pin Form
            '<section class="xray-section" id="pin-publish" style="margin-top:24px">'
            '<div class="eyebrow">Option 2 · Owner or Real Estate Agent Drop-a-Pin</div>'
            '<h2>Publish a Buy It Now or Auction Listing Now</h2>'
            '<p class="small">Click anywhere on the satellite map below (or search your address/town) to auto-detect county, state, elevation, flood zone, soil, and road proximity.</p>'
            '<div id="list-pin-map" class="map small" style="margin:12px 0"></div>'
            '<div id="list-xray-preview" class="callout" hidden style="margin-bottom:14px"></div>'
            '<form id="direct-list-form" class="worksheet">'
            '<label style="grid-column:1/-1"><span>1. Deal Mode (Buy It Now vs. Live Auction)</span>'
            '<div class="radio-pills">'
            '<label><input type="radio" name="sale_mode" value="buy_now" checked> Buy It Now (Fixed Price)</label>'
            '<label><input type="radio" name="sale_mode" value="auction"> Live Auction (Accept Bids)</label>'
            '</div></label>'
            '<label style="grid-column:1/-1"><span>2. Listing As</span>'
            '<div class="radio-pills">'
            '<label><input type="radio" name="seller_type" value="owner" checked> Landowner (FSBO)</label>'
            '<label><input type="radio" name="seller_type" value="agent"> Real Estate Agent / Broker</label>'
            '</div></label>'
            '<label style="grid-column:1/-1"><span>Find Location (Address, Town &amp; State, or GPS)</span>'
            '<span class="in"><input name="location" type="text" placeholder="e.g. Fredericksburg, TX or 30.275, -98.872">'
            '<button type="button" id="locate-pin-btn" class="button ghost sm" style="white-space:nowrap">Locate &amp; X-Ray</button></span></label>'
            '<label><span>Latitude</span><input name="lat" type="number" step="any" placeholder="Click map or locate" required></label>'
            '<label><span>Longitude</span><input name="lon" type="number" step="any" placeholder="Click map or locate" required></label>'
            '<label><span>Acreage</span><span class="in"><input name="acres" type="number" min="0.01" step="any" placeholder="10" required><i>acres</i></span></label>'
            '<label><span id="price-field-label">Buy It Now price ($)</span><span class="in"><input name="price" type="number" min="1" step="any" placeholder="25000" required><i>$</i></span></label>'
            '<div id="auction-only-fields" hidden style="grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px 16px;padding-top:8px;border-top:1px solid var(--line)">'
            '<label><span>Optional Buy It Now Price ($)</span><input name="buy_now_price" type="number" min="1" step="any" placeholder="Optional instant-buy price"></label>'
            '<label><span>Auction End Date/Time</span><input name="auction_end" type="datetime-local"></label>'
            '</div>'
            '<label><span>Listing Title (optional — auto-filled)</span><input name="title" type="text" placeholder="e.g. 10 Wooded Acres Near Lake"></label>'
            '<label><span>Parcel / APN (optional)</span><input name="apn" type="text" placeholder="County parcel ID"></label>'
            '<label><span>Zoning (optional)</span><input name="zoning" type="text" placeholder="Agricultural / Residential / Unrestricted"></label>'
            '<label><span>Road Access</span><input name="road_access" type="text" placeholder="Paved county road / recorded easement"></label>'
            '<label><span>Utilities</span><input name="utilities" type="text" placeholder="Power at road, well/septic needed"></label>'
            '<label class="inline-chk"><input name="financing_offered" type="checkbox"> Seller financing available</label>'
            '<label><span>Your Name (Owner or Agent)</span><input name="contact_name" type="text" required placeholder="Full name"></label>'
            '<label><span>Contact Email (private — for bids &amp; closing)</span><input name="contact_email" type="email" required placeholder="you@example.com"></label>'
            '<label><span>Phone (optional)</span><input name="contact_phone" type="tel" placeholder="(555) 123-4567"></label>'
            '<div id="agent-only-fields" hidden style="grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px 16px;padding-top:8px;border-top:1px solid var(--line)">'
            '<label><span>Brokerage Name</span><input name="brokerage" type="text" placeholder="e.g. Lone Star Land Realty"></label>'
            '<label><span>State License # (optional)</span><input name="agent_license" type="text" placeholder="License number"></label>'
            '</div>'
            '<label style="grid-column:1/-1"><span>Optional Direct Checkout / Escrow URL (Stripe Payment Link, Escrow.com, or Title Company)</span>'
            '<input name="checkout_url" type="url" placeholder="https://buy.stripe.com/... or https://escrow.com/... (optional)"></label>'
            '<label style="grid-column:1/-1"><span>Closing / Escrow Notes (optional)</span>'
            '<input name="escrow_notes" type="text" placeholder="e.g. Closes via First American Title; $1,000 earnest money"></label>'
            '<label style="grid-column:1/-1"><span>Plain Facts About the Land</span>'
            '<input name="notes" type="text" placeholder="Clear title, recent survey, timber, creek frontage, no HOA, etc."></label>'
            '<input name="website_hp" type="text" tabindex="-1" autocomplete="off" style="display:none">'
            '<div style="grid-column:1/-1;padding-top:6px"><button type="submit" id="publish-btn" class="button">Publish Listing Free →</button></div>'
            '</form>'
            '<div id="publish-result" class="callout" hidden style="margin-top:14px"></div>'
            '</section>'
            '</div>',
        ]
        desc = "List land for sale in any of the 50 U.S. states in 60 seconds—or let your AI agent (Claude, ChatGPT, Codex) publish Buy It Now or Auction listings via one API call with automatic 9-agency Federal Parcel X-Ray."
        return self.layout(
            "List Your Land Free (Owners, Real Estate Agents & AI Agents) | Landosaur",
            desc, "/list/", "".join(body), indexable=True, jsonld=[crumb_ld],
            scripts=["vendor/leaflet.js", "list.js"], wide=True,
        )

    # ------------------------------------------------------------------ /direct/ Direct Marketplace & Live Bidding/Checkout
    def direct_page(self):
        crumbs, crumb_ld = self.crumbs([("Direct Marketplace", "/direct/")])
        body = [
            crumbs,
            '<div id="direct-app">'
            '<h1>Direct by Owner &amp; Agent Land Marketplace</h1>'
            '<p class="lede">Live Buy It Now and Auction parcels listed directly by landowners, real estate agents, and AI agents across all 50 states—each auto-screened with 9 live federal GIS services. <a href="%s"><strong>List your land free →</strong></a></p>'
            '</div>' % self.u("/list/"),
        ]
        desc = "Browse, bid on, or Buy It Now direct owner and real estate agent land listings across all 50 U.S. states, complete with live 9-agency Federal Parcel X-Ray and real-time bidding."
        return self.layout(
            "Direct by Owner & Agent Land Marketplace — Bid or Buy It Now | Landosaur",
            desc, "/direct/", "".join(body), indexable=True, jsonld=[crumb_ld],
            scripts=["vendor/leaflet.js", "xray.js", "direct.js"], wide=True,
        )

    # ------------------------------------------------------------------ /services/ Land Agent & Buyer Services Hub
    def services_page(self):
        crumbs, crumb_ld = self.crumbs([("Land Agent & Buyer Services", "/services/")])
        body = [
            crumbs,
            '<div id="services-app">',
            '<div class="eyebrow">All 50 States · Listed &amp; Unlisted Land · $20 Initiation + 10% On Close</div>',
            '<h1>Landosaur Land Agent &amp; Buyer Services</h1>',
            '<p class="lede">Like DomainAgents for raw land. Pick <strong>any parcel listed on Landosaur</strong>—or drop a pin on <strong>any unlisted, off-market parcel in America</strong>. Pay <strong>$20 to start</strong> and our acquisition desk handles county title/tax verification, agency bidding or landowner outreach, paperwork, and licensed title/deed transfer for a transparent <strong>10% concierge fee only when your deal closes</strong>.</p>',

            '<section class="dossier-card" style="margin-top:18px">'
            '<div class="eyebrow">How Land Agent Works</div>'
            '<div class="card-grid" style="margin-top:10px">'
            '<article class="info-card"><div class="eyebrow">Step 1 · $20 Today</div><h3>Lock In Any Parcel</h3><p>Submit a Landosaur parcel ID, county APN, address, or satellite pin anywhere in all 50 states. Pay $20 to open your live acquisition dossier.</p></article>'
            '<article class="info-card"><div class="eyebrow">Step 2 · We Do the Legwork</div><h3>Verify, Contact &amp; Submit</h3><p>We run 9-agency GIS screening, check county tax/lien/redemption status, prepare municipal applications or auction bids, or contact unlisted landowners directly.</p></article>'
            '<article class="info-card"><div class="eyebrow">Step 3 · 10% Only On Close</div><h3>Licensed Title &amp; Deed Transfer</h3><p>We coordinate closing through a licensed title company or closing attorney in the parcel\'s state so your deed records cleanly into your name.</p></article>'
            '</div></section>',

            '<section><h2>Every Land Buyer Service Under One Roof</h2>'
            '<p class="small">Click any service card below to select it and pre-configure your $20 Land Agent initiation form.</p>'
            '<div class="card-grid">'
            '<article class="info-card service-card" data-select-service="listed_acquisition" style="cursor:pointer">'
            '<div class="eyebrow">$20 Start + 10% Transfer Fee</div>'
            '<h3>Buy &amp; Transfer Listed Public Land</h3>'
            '<p>Full hands-free acquisition for any fixed-price, OTC, or surplus government parcel in our 50-state database—application prep, payment routing, and deed recording.</p>'
            '<span class="card-link">Select Listed Acquisition →</span></article>'

            '<article class="info-card service-card" data-select-service="unlisted_outreach" style="cursor:pointer">'
            '<div class="eyebrow">Off-Market · All 50 States · $20 + 10%</div>'
            '<h3>Unlisted &amp; Off-Market Land Acquisition</h3>'
            '<p>Found a parcel that isn\'t even for sale? Drop a pin or paste the APN—we pull county ownership records, run 9-agency X-Ray, make outreach with your offer, and coordinate closing.</p>'
            '<span class="card-link">Select Unlisted Land Agent →</span></article>'

            '<article class="info-card service-card" data-select-service="auction_proxy" style="cursor:pointer">'
            '<div class="eyebrow">Tax Deeds &amp; Auctions · $20 + 10%</div>'
            '<h3>Tax-Sale &amp; Public Auction Concierge</h3>'
            '<p>Statutory redemption verification, back-tax &amp; municipal lien checks, bidder registration packet prep, and maximum-bid strategy across county &amp; state auctions.</p>'
            '<span class="card-link">Select Auction Concierge →</span></article>'

            '<article class="info-card service-card" data-select-service="landbank_application" style="cursor:pointer">'
            '<div class="eyebrow">City &amp; County Land Banks · $20 + 10%</div>'
            '<h3>Land Bank &amp; Side-Lot Application Desk</h3>'
            '<p>Side-lot eligibility checks, municipal development/rehab packets, zoning confirmation, and board-approval tracking across 30+ city and county land banks.</p>'
            '<span class="card-link">Select Land Bank Concierge →</span></article>'

            '<article class="info-card service-card" data-select-service="diligence_packet" style="cursor:pointer">'
            '<div class="eyebrow">Deep Field &amp; Title Audit · $20 Deposit</div>'
            '<h3>Full Pre-Purchase Diligence Packet</h3>'
            '<p>Recorded legal road easement check, county tax &amp; lien scan, septic/perc &amp; well depth review, utility line extension inquiry, and survey/attorney coordination.</p>'
            '<span class="card-link">Select Diligence Audit →</span></article>'

            '<article class="info-card service-card" data-select-service="custom_sourcing" style="cursor:pointer">'
            '<div class="eyebrow">Investors &amp; Homesteaders · $20 Start</div>'
            '<h3>Custom Acreage &amp; Portfolio Sourcing</h3>'
            '<p>Tell us your target states, acreage, budget, and use (homestead, hunting, timber, solar, RV/glamping, subdivision)—we source both public &amp; off-market matches.</p>'
            '<span class="card-link">Select Custom Sourcing →</span></article>'
            '</div></section>',

            '<section class="dossier-card" id="start-land-agent" style="margin-top:26px">'
            '<div class="eyebrow">Initiate Your Acquisition · $20 Today</div>'
            '<h2>Start Your Land Agent Acquisition &amp; Transfer</h2>'
            '<div id="selected-parcel-banner" class="callout" hidden style="margin:10px 0 14px"></div>'
            '<form id="concierge-form" class="worksheet">'
            '<label style="grid-column:1/-1"><span>Buyer Service Type</span><select name="service_type">'
            '<option value="listed_acquisition">Listed Public Land Acquisition &amp; Full Transfer ($20 + 10% on close)</option>'
            '<option value="unlisted_outreach">Unlisted / Off-Market Parcel Acquisition ($20 + 10% on close)</option>'
            '<option value="auction_proxy">Tax-Sale &amp; Public Auction Concierge ($20 + 10% on close)</option>'
            '<option value="landbank_application">Land Bank &amp; Side-Lot Application Service ($20 + 10% on close)</option>'
            '<option value="diligence_packet">Deep Pre-Purchase Title, Easement &amp; Diligence Audit ($20 deposit)</option>'
            '<option value="custom_sourcing">Custom Acreage / Off-Market Portfolio Sourcing ($20 initiation)</option>'
            '</select></label>'

            '<div id="unlisted-pin-wrap" style="grid-column:1/-1">'
            '<p class="small" style="margin:0 0 8px"><strong>Targeting an unlisted or off-market parcel?</strong> Click anywhere on the satellite map or search an address/town below to auto-detect county, state, elevation, flood zone, and road distance.</p>'
            '<div id="concierge-pin-map" class="map small" style="margin-bottom:10px"></div>'
            '<div id="concierge-xray-preview" class="callout" hidden style="margin-bottom:10px"></div>'
            '</div>'

            '<label style="grid-column:1/-1"><span>Search Address, Town, or Unlisted Location (optional)</span>'
            '<div style="display:flex;gap:8px;flex-wrap:wrap"><input name="location" type="text" placeholder="e.g. 1206 SW Munson Ave, Topeka, KS or rural highway near Bozeman, MT" style="flex:1 1 260px">'
            '<button type="button" id="concierge-locate-btn" class="button ghost sm">Locate &amp; X-Ray</button></div></label>'

            '<label><span>Landosaur Parcel ID (if listed)</span><input name="parcel_id" type="text" placeholder="e.g. ks-snco-0973604015014000"></label>'
            '<label><span>County Parcel / APN (if known)</span><input name="apn" type="text" placeholder="Assessor parcel number"></label>'
            '<label><span>County</span><input name="county" type="text" placeholder="e.g. Shawnee County"></label>'
            '<label><span>State (2-letter)</span><input name="state" type="text" maxlength="2" placeholder="e.g. KS"></label>'
            '<label><span>Latitude (auto-filled by pin)</span><input name="lat" type="number" step="any" placeholder="39.04"></label>'
            '<label><span>Longitude (auto-filled by pin)</span><input name="lon" type="number" step="any" placeholder="-95.69"></label>'
            '<label><span>Parcel Title / Short Label</span><input name="parcel_title" type="text" placeholder="Optional parcel label"></label>'
            '<label><span>Stated Acres (optional)</span><input name="acres" type="number" step="any" min="0" placeholder="e.g. 5"></label>'
            '<label><span>Official Agency Price / Min Bid ($)</span><input name="official_price" type="number" step="any" min="0" placeholder="Leave blank if unlisted / unpriced"></label>'
            '<label><span>Your Max Offer / Budget ($)</span><input name="max_budget" type="number" step="any" min="0" placeholder="e.g. 15000"></label>'
            '<label><span>Funding Type</span><select name="financing"><option value="cash">All cash / wire at closing</option><option value="land_loan">Land loan</option><option value="seller_financing">Open to seller financing</option></select></label>'
            '<label><span>Your Full Name</span><input name="buyer_name" type="text" required placeholder="Full legal name for closing"></label>'
            '<label><span>Your Email</span><input name="buyer_email" type="email" required placeholder="you@example.com"></label>'
            '<label><span>Phone (optional)</span><input name="buyer_phone" type="tel" placeholder="(555) 123-4567"></label>'
            '<label style="grid-column:1/-1"><span>Special Instructions, Intended Use, or Contingencies</span>'
            '<input name="notes" type="text" placeholder="e.g. Confirm legal road access before bidding; LLC vest title; looking for 5-20 wooded acres"></label>'
            '<input name="website_hp" type="text" tabindex="-1" autocomplete="off" style="display:none">'

            '<div class="fee-ledger" id="fee-breakdown-live" style="grid-column:1/-1"></div>'
            '<div style="grid-column:1/-1;padding-top:4px"><button type="submit" id="concierge-submit" class="button" data-vital-event="offer_clicked">Start Acquisition with Land Agent — $20 →</button></div>'
            '</form>'
            '<div id="concierge-result" class="callout" hidden style="margin-top:14px"></div>'
            '<p class="small" style="margin-top:14px"><strong>Transparency &amp; Licensing Notice:</strong> Landosaur is an independent land intelligence platform and acquisition concierge—not a government agency. The $20 initiation fee begins parcel-specific research, verification, paperwork prep, or off-market outreach. The transparent 10% concierge transfer fee applies only when an acquisition successfully closes. Wherever state law requires a licensed real estate broker, title agent, or closing attorney to represent a buyer or execute deed conveyance, Landosaur coordinates directly through a licensed local partner in that state.</p>'
            '</section>',

            '<section class="dossier-card" style="margin-top:20px">'
            '<h2>Track an Existing Land Agent Order</h2>'
            '<form id="track-order-form" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">'
            '<input name="code" type="text" placeholder="Enter confirmation code (e.g. AGT-1A2B3C4D)" style="flex:1 1 240px;padding:9px 12px;border:1px solid var(--line-strong);border-radius:10px;background:var(--surface-2);color:var(--ink)">'
            '<button type="submit" class="button ghost sm">Check Order Status</button></form>'
            '<div id="track-order-out" class="callout" hidden style="margin-top:10px"></div>'
            '</section>',
            '</div>',
        ]
        desc = "Hire Landosaur's Land Agent ($20 initiation + transparent 10% transfer fee on close) to buy and transfer listed public land or acquire unlisted off-market parcels across all 50 U.S. states."
        return self.layout(
            "Land Agent & Buyer Services — Buy Listed or Unlisted Land ($20 to Start) | Landosaur",
            desc, "/services/", "".join(body), indexable=True, jsonld=[crumb_ld],
            scripts=["vendor/leaflet.js", "services.js"], wide=True,
        )

    # ------------------------------------------------------------------ /land-atlas/ U.S. Land Data Atlas & Interactive Charts
    def land_atlas_page(self):
        cat = self.cat
        m = self.market
        cur = cat.current()
        us = m.latest_values("US")
        chg, y0, y1 = m.span_change("US", "farm_real_estate")
        crumbs, crumb_ld = self.crumbs([("U.S. Land Data Atlas & Charts", "/land-atlas/")])
        body = [
            crumbs,
            '<div id="atlas-app">',
            '<div class="eyebrow">All 50 States · 2010–%d USDA NASS · 3,115 U.S. Counties · Live Public Supply</div>' % m.latest_year,
            '<h1>U.S. Land Data Atlas &amp; Interactive Market Charts</h1>',
            '<p class="lede">The open reference atlas for American land—combining <strong>%s live public-agency parcels across all %d U.S. states (%d agencies)</strong>, <strong>17 years of official USDA NASS agricultural land values (%d–%d)</strong>, and searchable benchmarks across <strong>all 3,115 U.S. counties</strong>. Zero fabricated metrics.</p>' % (
                "{:,}".format(len(cur)), len(cat.states), len(adapters.SOURCES), m.first_year, m.latest_year),

            '<div class="kpi-grid">'
            '<div class="kpi-card"><span>Live Official Database</span><strong>%s</strong><small>Active parcels · %d/50 states · %d agencies</small></div>'
            '<div class="kpi-card"><span>U.S. Farm Real Estate (%d)</span><strong>%s/ac</strong><small>USDA NASS national benchmark</small></div>'
            '<div class="kpi-card"><span>%d–%d Nominal Growth</span><strong>%s</strong><small>U.S. agricultural land appreciation</small></div>'
            '<div class="kpi-card"><span>County Benchmark Coverage</span><strong>3,115</strong><small>Every U.S. county searchable &amp; CSV-ready</small></div>'
            '</div>' % (
                "{:,}".format(len(cur)), len(cat.states), len(adapters.SOURCES),
                m.latest_year, esc(market_mod.usd(us.get("farm_real_estate"))),
                y0 or m.first_year, y1 or m.latest_year, esc(market_mod.pct(chg)),
            ),

            '<section class="dossier-card" style="margin-top:24px">'
            '<div class="eyebrow">Interactive 50-State Cartogram</div>'
            '<h2>Compare All 50 States at a Glance</h2>'
            '<div class="atlas-controls">'
            '<button type="button" class="mode-btn active" data-carto-metric="fre">2026 Price ($/acre)</button>'
            '<button type="button" class="mode-btn" data-carto-metric="chg16">2010–%d Appreciation (%%)</button>'
            '<button type="button" class="mode-btn" data-carto-metric="chg5">5-Year Growth (%%)</button>'
            '<button type="button" class="mode-btn" data-carto-metric="active">Live Landosaur Parcels</button>'
            '</div>'
            '<div id="atlas-cartogram" class="us-cartogram" aria-label="Interactive 50-state U.S. land data cartogram"></div>'
            '<p id="cartogram-readout" class="small" style="margin-top:10px">Hover any state tile to inspect 2026 $/acre, historical appreciation, and live official parcel count. Click any state to explore.</p>'
            '</section>' % m.latest_year,

            '<section class="dossier-card" style="margin-top:24px">'
            '<div class="eyebrow">Interactive Multi-State Time Series (%d–%d)</div>'
            '<h2>Compare Land Value Growth Across Any 4 States</h2>'
            '<div class="atlas-controls">'
            '<label>Series 1 <select id="cmp-st-1"></select></label>'
            '<label>Series 2 <select id="cmp-st-2"></select></label>'
            '<label>Series 3 <select id="cmp-st-3"></select></label>'
            '<label>Series 4 <select id="cmp-st-4"></select></label>'
            '<label>Land Class <select id="cmp-metric"><option value="farm_real_estate">Farm Real Estate</option><option value="cropland">Cropland</option><option value="pasture">Pasture</option></select></label>'
            '<label>Scale <select id="cmp-scale"><option value="usd">Nominal $/acre</option><option value="index">Indexed Growth (Start = 100)</option></select></label>'
            '</div>'
            '<div id="atlas-compare-chart" style="margin-top:12px"></div>'
            '<div id="atlas-compare-stats" class="kpi-grid" style="margin-top:12px"></div>'
            '</section>' % (m.first_year, m.latest_year),

            '<section class="dossier" style="margin-top:24px">'
            '<div class="dossier-card"><div class="eyebrow">Live 50-State Official Supply</div><h2>Top States by Active Official Parcels</h2><div id="atlas-top-states"></div></div>'
            '<div class="dossier-card"><div class="eyebrow">Inventory Structure</div><h2>Deal Modes &amp; Acreage Size Distribution</h2>'
            '<h3 style="margin-top:10px">By Sale Type</h3><div id="atlas-mode-split"></div>'
            '<h3 style="margin-top:18px">By Stated Acreage Tier</h3><div id="atlas-acre-tiers"></div></div>'
            '</section>',

            '<section class="dossier-card" style="margin-top:24px">'
            '<div class="eyebrow">Public-Sale Pricing vs. Market Averages</div>'
            '<h2>Live Priced Public Offerings vs. USDA State Averages</h2>'
            '<p class="small">Computed strictly from live official listings carrying both a published price/minimum bid and stated acreage—never blended with unpriced land-bank parcels.</p>'
            '<div id="atlas-discount-table"></div>'
            '</section>',

            '<section class="dossier-card" style="margin-top:24px">'
            '<div class="eyebrow">All 3,115 U.S. Counties · Searchable &amp; Exportable</div>'
            '<h2>U.S. County Land Value Explorer (%d)</h2>'
            '<div class="atlas-controls">'
            '<label>State <select id="county-st-filter"></select></label>'
            '<label>Search County <input id="county-q-filter" type="search" placeholder="e.g. Gallatin, Shawnee, Coconino"></label>'
            '<label>Sort <select id="county-sort"><option value="val_asc">Lowest $/acre first</option><option value="val_desc">Highest $/acre first</option><option value="name_asc">County A–Z</option></select></label>'
            '<button type="button" id="county-export-csv" class="button ghost sm" style="margin-left:auto">Export Filtered CSV</button>'
            '</div>'
            '<p id="county-explorer-count" class="small" style="margin:8px 0"></p>'
            '<div class="scroll"><table class="data"><thead><tr><th>County</th><th>State</th><th class="n">2026 Benchmark</th><th class="n">vs. State Avg</th><th>Action</th></tr></thead><tbody id="county-explorer-body"></tbody></table></div>'
            '</section>',

            '<section class="callout" style="margin-top:24px"><h2>Want to buy land in any county above—even if it isn\'t listed yet?</h2>'
            '<p>Use our <a href="%s"><strong>$20 Land Agent Concierge</strong></a> for listed or unlisted off-market parcels across all 50 states, download raw datasets on <a href="%s">/data/</a>, or inspect individual state histories on <a href="%s">/land-prices/</a>.</p></section>' % (
                self.u("/services/"), self.u("/data/"), self.u("/land-prices/")),
            '</div>',
        ]
        desc = "Interactive U.S. Land Data Atlas: 50-state land value cartogram, 2010–%d USDA multi-state appreciation charts, live supply breakdowns across %s parcels, and searchable 3,115-county price explorer." % (
            m.latest_year, "{:,}".format(len(cur)))
        return self.layout(
            "U.S. Land Data Atlas — 50-State Charts, 3,115 County Prices & Live Supply | Landosaur",
            desc, "/land-atlas/", "".join(body), indexable=True, jsonld=[crumb_ld],
            scripts=["atlas.js"], wide=True,
        )

    # ------------------------------------------------------------------ /land-for-sale/ (national directory)
    def land_for_sale_index(self):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("Land for Sale", "/land-for-sale/")])
        cur = cat.current()
        active_cards = []
        for st in sorted(cat.states.values(), key=lambda s: -sum(1 for r in s["listings"] if r["available"])):
            avail = [r for r in st["listings"] if r["available"]]
            priced = [r["price"] for r in avail if r.get("price") is not None]
            low = money(min(priced)) if priced else "Offer / app"
            active_cards.append(
                '<article class="info-card"><div class="eyebrow">%s · %d %s</div>'
                '<h3><a href="%s">%s Land for Sale</a></h3>'
                '<p><strong>%s</strong> active official offerings · Starting from %s.</p>'
                '<a class="card-link" href="%s">Browse %s parcels →</a></article>' % (
                    esc(st["code"]), len(st["counties"]), "jurisdiction" if len(st["counties"]) == 1 else "jurisdictions",
                    self.u(cat.state_path(st)), esc(st["name"]),
                    "{:,}".format(len(avail)), esc(low),
                    self.u(cat.state_path(st)), esc(st["name"]),
                )
            )
        all_tiles = []
        for st in self.all_states:
            href = self.u(st["browse_path"]) if st["browse_path"] else self.u(st["path"])
            sub = "%s live listings" % "{:,}".format(st["active_count"]) if st["active_count"] else "Price history & counties"
            val_txt = "%s/ac" % market_mod.usd(st["values"].get("farm_real_estate")) if st["values"].get("farm_real_estate") else (
                "%s/ac county med." % market_mod.usd(st["county_median"]) if st["county_median"] else "View benchmarks"
            )
            all_tiles.append(
                '<a class="state-tile" href="%s"><strong>%s</strong><span>%s</span><small>%s</small></a>' % (
                    href, esc(st["name"]), esc(val_txt), esc(sub),
                )
            )
        body = [
            crumbs,
            '<h1>Official Government, Tax-Sale &amp; Rural Land for Sale by State</h1>',
            '<p class="lede">Browse <strong>%s</strong> live public-agency parcels across %d tracked states, or inspect %d USDA/FHFA land prices per acre and county benchmarks across all 50 states.</p>' % (
                "{:,}".format(len(cur)), len(cat.states), self.market.latest_year),
            '<section><h2>States with live official inventories (%d tracked)</h2><div class="card-grid">%s</div></section>' % (
                len(cat.states), "".join(active_cards)),
            '<section><h2>All 50 U.S. states — listings &amp; %d land price benchmarks</h2>'
            '<p class="small">States with live agency connectors open directly to active listings; all other states open their %d USDA &amp; county land price reference hub.</p>'
            '<div class="state-grid">%s</div></section>' % (self.market.latest_year, self.market.latest_year, "".join(all_tiles)),
            '<section class="callout"><h2>Evaluating a parcel you found elsewhere?</h2>'
            '<p>Run any parcel through our free <a href="%s"><strong>Land Valuation, Financing &amp; Electricity Analyzer</strong></a> or read our <a href="%s">29 land due-diligence guides</a>.</p></section>' % (
                self.u("/analyze/"), self.u("/research/#field-guides")),
        ]
        desc = "Browse %s live government, tax-sale, state trust, and land-bank parcels across %d U.S. states, plus 50-state USDA/FHFA per-acre land price hubs." % (
            "{:,}".format(len(cur)), len(cat.states))
        ld = [crumb_ld, {
            "@context": "https://schema.org", "@type": "ItemList",
            "name": "U.S. States with Land Listings and Land Price Benchmarks",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": st["name"], "url": self.absu(st["browse_path"] or st["path"])}
                for i, st in enumerate(self.all_states)
            ],
        }]
        return self.layout(
            "Land for Sale by State — Government, Auction & Rural Parcels | Landosaur",
            desc, "/land-for-sale/", "".join(body), indexable=True, jsonld=ld, wide=True,
        )

    # ------------------------------------------------------------------ /land-prices/ observatory (56 pages)
    def land_prices_nav(self, current_path):
        links = [
            ("/land-prices/", "Overview"),
            ("/land-prices/states/", "50-State Rankings"),
            ("/land-prices/cheapest-land-per-acre/", "Cheapest Per Acre"),
            ("/land-prices/history/", "2010–%d History" % self.market.latest_year),
            ("/land-prices/by-acreage/", "By Acreage"),
            ("/land-prices/data-methodology/", "Data & Methods"),
        ]
        return '<nav class="research-jumps" aria-label="Land price observatory">%s</nav>' % "".join(
            '<a href="%s"%s>%s</a>' % (self.u(p), ' style="background:var(--lime-soft);border-color:var(--forest)"' if p == current_path else "", esc(lbl))
            for p, lbl in links
        )

    def land_prices_index(self):
        m = self.market
        crumbs, crumb_ld = self.crumbs([("Land Prices", "/land-prices/")])
        us = m.latest_values("US")
        chg, y0, y1 = m.span_change("US", "farm_real_estate")
        cheapest = m.cheapest_listings(8)
        state_tiles = "".join(
            '<a class="state-tile" href="%s"><strong>%s</strong><span>%s</span><small>%s</small></a>' % (
                self.u(st["path"]), esc(st["name"]),
                "%s/ac" % market_mod.usd(st["values"].get("farm_real_estate")) if st["published"] else (
                    "%s/ac med." % market_mod.usd(st["county_median"]) if st["county_median"] else "County data"
                ),
                ("#%d lowest · %d counties" % (st["rank"], st["county_count"])) if st["rank"] else "%d counties" % st["county_count"],
            )
            for st in self.all_states
        )
        body = [
            crumbs,
            '<div class="eyebrow">50-State Land Price Observatory · USDA NASS &amp; FHFA</div>',
            '<h1>Land Prices Per Acre Across All 50 States (%d)</h1>' % m.latest_year,
            '<p class="lede">Compare official USDA NASS agricultural land values (%d–%d), 3,115 county-level benchmarks, and live public-agency asking prices and minimum bids. Every series stays clearly separated by source and definition.</p>' % (
                m.first_year, m.latest_year),
            self.land_prices_nav("/land-prices/"),
            '<div class="kpi-grid">'
            '<div class="kpi-card"><span>U.S. Farm Real Estate (%d)</span><strong>%s/ac</strong><small>USDA NASS · land &amp; buildings</small></div>'
            '<div class="kpi-card"><span>U.S. Cropland (%d)</span><strong>%s/ac</strong><small>USDA NASS national survey</small></div>'
            '<div class="kpi-card"><span>U.S. Pasture (%d)</span><strong>%s/ac</strong><small>USDA NASS national survey</small></div>'
            '<div class="kpi-card"><span>%d–%d Nominal Change</span><strong>%s</strong><small>U.S. farm real estate</small></div>'
            '</div>' % (
                m.latest_year, esc(market_mod.usd(us.get("farm_real_estate"))),
                m.latest_year, esc(market_mod.usd(us.get("cropland"))),
                m.latest_year, esc(market_mod.usd(us.get("pasture"))),
                y0 or m.first_year, y1 or m.latest_year, esc(market_mod.pct(chg)),
            ),
            '<section><h2>U.S. land value history (%d–%d)</h2>%s<p><a href="%s">Inspect the full annual table &amp; sources →</a></p></section>' % (
                m.first_year, m.latest_year, m.svg_trend_chart("US", "U.S. agricultural land values per acre, 2010 to %d" % m.latest_year),
                self.u("/land-prices/history/")),
            '<section><h2>Explore by state (all 50 states + 3,115 counties)</h2><div class="state-grid">%s</div></section>' % state_tiles,
        ]
        if cheapest:
            body.append(
                '<section><h2>Lowest published price or minimum bid per acre in our live catalog</h2>'
                '<p class="small">Official agency listings only—minimum bids are opening floors, not final prices or appraisals.</p>'
                '%s<p><a href="%s">See the complete cheapest-per-acre ranking →</a></p></section>' % (
                    self.rows(cheapest, True, True), self.u("/land-prices/cheapest-land-per-acre/"))
            )
        desc = "Explore %d land prices per acre across all 50 U.S. states: USDA farm real estate (%s/acre U.S.), cropland, pasture, 2010-%d history charts, 3,115 county benchmarks, and cheapest official offerings." % (
            m.latest_year, market_mod.usd(us.get("farm_real_estate")), m.latest_year)
        ld = [{"@context": "https://schema.org", "@graph": [
            self.org_node(),
            {k: v for k, v in crumb_ld.items() if k != "@context"},
            {
                "@type": "Dataset", "@id": self.absu("/land-prices/#dataset"),
                "name": "U.S. 50-State & County Land Prices Per Acre Observatory (%d-%d)" % (m.first_year, m.latest_year),
                "description": desc, "url": self.absu("/land-prices/"), "isAccessibleForFree": True,
                "creator": {"@id": self.absu("/#organization")},
                "temporalCoverage": "%d/%d" % (m.first_year, m.latest_year), "spatialCoverage": "United States",
            },
        ]}]
        return self.layout(
            "Land Prices Per Acre by State (%d): Charts, County Values & Live Listings | Landosaur" % m.latest_year,
            desc, "/land-prices/", "".join(body), indexable=True, jsonld=ld, scripts=["tables.js"], wide=True,
        )

    def land_prices_states(self):
        m = self.market
        crumbs, crumb_ld = self.crumbs([("Land Prices", "/land-prices/"), ("State Rankings", "/land-prices/states/")])
        rows = []
        for st in sorted(self.all_states, key=lambda s: (s["values"].get("farm_real_estate") is None, s["values"].get("farm_real_estate") or 0, s["name"])):
            v = st["values"]
            rows.append(
                '<tr><td class="n" data-v="%s">%s</td><th scope="row"><a href="%s">%s</a></th>'
                '<td class="n" data-v="%s">%s</td><td class="n" data-v="%s">%s</td><td class="n" data-v="%s">%s</td>'
                '<td class="n" data-v="%s">%s</td><td class="n" data-v="%s">%s</td><td class="n" data-v="%d">%s</td></tr>' % (
                    st["rank"] or 999, "#%d" % st["rank"] if st["rank"] else "–",
                    self.u(st["path"]), esc(st["name"]),
                    v.get("farm_real_estate") or "", esc(market_mod.usd(v.get("farm_real_estate"), dash="Excluded")),
                    v.get("cropland") or "", esc(market_mod.usd(v.get("cropland"), dash="–")),
                    v.get("pasture") or "", esc(market_mod.usd(v.get("pasture"), dash="–")),
                    st["change_pct"] if st["change_pct"] is not None else "", esc(market_mod.pct(st["change_pct"], dash="–")),
                    st["county_median"] or "", esc(market_mod.usd(st["county_median"], dash="–")),
                    st["active_count"],
                    ('<a href="%s">%s</a>' % (self.u(st["browse_path"]), "{:,}".format(st["active_count"]))) if st["active_count"] else "0",
                )
            )
        body = [
            crumbs,
            '<h1>Land Prices by State (%d): All 50 States Ranked Per Acre</h1>' % m.latest_year,
            '<p class="lede">Click any column header to sort all 50 states by %d USDA farm real estate, cropland, pasture, %d–%d nominal change, county median, or live Landosaur inventory. Alaska and Hawaii are excluded from USDA\'s contiguous-48 series and shown honestly.</p>' % (
                m.latest_year, m.first_year, m.latest_year),
            self.land_prices_nav("/land-prices/states/"),
            '<div class="scroll"><table class="data sortable"><thead><tr>'
            '<th scope="col" class="n">Rank</th><th scope="col">State</th>'
            '<th scope="col" class="n">Farm Real Estate</th><th scope="col" class="n">Cropland</th>'
            '<th scope="col" class="n">Pasture</th><th scope="col" class="n">%d–%d Chg</th>'
            '<th scope="col" class="n">County Median</th><th scope="col" class="n">Live Listings</th>'
            '</tr></thead><tbody>%s</tbody></table></div>' % (m.first_year, m.latest_year, "".join(rows)),
        ]
        desc = "Compare %d land prices per acre across all 50 U.S. states: USDA farm real estate, cropland, pasture, 2010-%d appreciation, and county medians." % (m.latest_year, m.latest_year)
        return self.layout(
            "Land Prices by State (%d) — All 50 States Ranked Per Acre | Landosaur" % m.latest_year,
            desc, "/land-prices/states/", "".join(body), indexable=True, jsonld=[crumb_ld], scripts=["tables.js"], wide=True,
        )

    def land_prices_cheapest(self):
        crumbs, crumb_ld = self.crumbs([("Land Prices", "/land-prices/"), ("Cheapest Per Acre", "/land-prices/cheapest-land-per-acre/")])
        all_cheap = self.market.cheapest_listings(150)
        fixed = [r for r in all_cheap if r.get("price_kind") == "cash"]
        bids = [r for r in all_cheap if r.get("price_kind") == "min_bid"]
        body = [
            crumbs,
            '<h1>Cheapest Official Land Per Acre in the Live Catalog</h1>',
            '<p class="lede">Ranked from lowest published price or minimum bid per acre across active official public-agency offerings (%s snapshot). Fixed over-the-counter prices and tax-sale minimum bids are separated clearly—always review access, title, and total all-in cost before bidding.</p>' % esc(self.updated()),
            self.land_prices_nav("/land-prices/cheapest-land-per-acre/"),
            '<div class="kpi-grid">'
            '<div class="kpi-card"><span>Ranked Priced Parcels</span><strong>%s</strong><small>With both price &amp; acres published</small></div>'
            '<div class="kpi-card"><span>Fixed-Price OTC</span><strong>%s</strong><small>State &amp; trust land fixed prices</small></div>'
            '<div class="kpi-card"><span>Auction Minimum Bids</span><strong>%s</strong><small>Opening bid floors, not final sales</small></div>'
            '<div class="kpi-card"><span>Lowest Published $/Acre</span><strong>%s</strong><small>Inspect terms &amp; access on dossier</small></div>'
            '</div>' % (
                "{:,}".format(len(all_cheap)), "{:,}".format(len(fixed)), "{:,}".format(len(bids)),
                esc(money(all_cheap[0]["price"] / all_cheap[0]["acres"]) + "/ac") if all_cheap else "–",
            ),
        ]
        if fixed:
            body.append('<section><h2>Fixed-price over-the-counter state &amp; trust land (%d)</h2>%s</section>' % (
                len(fixed), self.rows(fixed, True, True)))
        if bids:
            body.append('<section><h2>Lowest auction minimum bid per acre (%d)</h2><p class="small">Opening minimum bids only—winning bids, back taxes, quiet-title work, and site access can significantly change total cost.</p>%s</section>' % (
                len(bids), self.rows(bids, True, True)))
        desc = "Compare the lowest-priced official government and auction land offerings per acre (%s): fixed over-the-counter state trust land and tax-sale minimum bids with direct agency links." % self.updated()
        return self.layout(
            "Cheapest Land Per Acre — Live Official & Auction Offerings | Landosaur",
            desc, "/land-prices/cheapest-land-per-acre/", "".join(body), indexable=True, jsonld=[crumb_ld], scripts=["tables.js"], wide=True,
        )

    def land_prices_history(self):
        m = self.market
        crumbs, crumb_ld = self.crumbs([("Land Prices", "/land-prices/"), ("Price History", "/land-prices/history/")])
        years = list(range(m.first_year, m.latest_year + 1))
        fre = {o["year"]: o["valueUsdPerAcre"] for o in m.series("US", "farm_real_estate")}
        crop = {o["year"]: o["valueUsdPerAcre"] for o in m.series("US", "cropland")}
        past = {o["year"]: o["valueUsdPerAcre"] for o in m.series("US", "pasture")}
        rows = []
        prev = None
        for y in years:
            fv = fre.get(y)
            yoy = ((fv / float(prev) - 1.0) * 100.0) if (fv and prev) else None
            rows.append(
                '<tr><th scope="row">%d</th><td class="n" data-v="%s">%s</td><td class="n" data-v="%s">%s</td>'
                '<td class="n" data-v="%s">%s</td><td class="n" data-v="%s">%s</td></tr>' % (
                    y, fv or "", esc(market_mod.usd(fv)),
                    crop.get(y) or "", esc(market_mod.usd(crop.get(y))),
                    past.get(y) or "", esc(market_mod.usd(past.get(y))),
                    "%.1f" % yoy if yoy is not None else "", esc(market_mod.pct(yoy, dash="–")),
                )
            )
            if fv:
                prev = fv
        src_lis = "".join(
            '<li><a href="%s" rel="noopener noreferrer">%s</a> (%d–%d, published %s)</li>' % (
                esc(s["url"]), esc(s["title"]), s["firstDataYear"], s["lastDataYear"], esc(s["publicationDate"]))
            for s in (m.usda.get("sources", []) if m.usda else [])
        )
        body = [
            crumbs,
            '<h1>U.S. Land Price History (%d–%d): Annual USDA Values Per Acre</h1>' % (m.first_year, m.latest_year),
            '<p class="lede">Historical nominal USD per acre for U.S. farm real estate, cropland, and pasture from official USDA NASS Agricultural Land Values reports. Missing or withheld observations remain gaps.</p>',
            self.land_prices_nav("/land-prices/history/"),
            m.svg_trend_chart("US", "U.S. annual agricultural land values per acre, %d to %d" % (m.first_year, m.latest_year)),
            '<section><h2>Annual U.S. land value table (%d–%d)</h2><div class="scroll"><table class="data sortable"><thead><tr>'
            '<th scope="col">Year</th><th scope="col" class="n">Farm Real Estate</th><th scope="col" class="n">Cropland</th>'
            '<th scope="col" class="n">Pasture</th><th scope="col" class="n">YoY Change</th></tr></thead><tbody>%s</tbody></table></div></section>' % (
                m.first_year, m.latest_year, "".join(reversed(rows))),
            '<section><h2>Primary USDA NASS Source Publications</h2><ul class="notes">%s</ul></section>' % src_lis,
        ]
        desc = "Historical U.S. land prices per acre from %d to %d: official USDA NASS farm real estate, cropland, and pasture series with annual table and primary source citations." % (m.first_year, m.latest_year)
        return self.layout(
            "U.S. Land Price History (%d–%d) — Annual Values Per Acre | Landosaur" % (m.first_year, m.latest_year),
            desc, "/land-prices/history/", "".join(body), indexable=True, jsonld=[crumb_ld], scripts=["tables.js"], wide=True,
        )

    def land_prices_by_acreage(self):
        crumbs, crumb_ld = self.crumbs([("Land Prices", "/land-prices/"), ("By Acreage", "/land-prices/by-acreage/")])
        bands = self.market.acreage_bands()
        rows = "".join(
            '<tr><th scope="row">%s</th><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
            '<td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
                esc(b["label"]), "{:,}".format(b["count"]), "{:,}".format(b["cash_count"]), "{:,}".format(b["bid_count"]),
                esc(research.fmt_acres(b["total_acres"])),
                esc(money(b["median_price"], "–")), esc(money(b["median_ppa"], "–")), esc(money(b["min_ppa"], "–")),
            )
            for b in bands
        )
        body = [
            crumbs,
            '<h1>Land Asking Prices &amp; Minimum Bids by Acreage Band</h1>',
            '<p class="lede">Small city and subdivision lots trade at much higher implied prices per acre than rural multi-acre tracts, while larger tracts require bigger total cash commitments. Computed directly from the %s active catalog.</p>' % esc(self.updated()),
            self.land_prices_nav("/land-prices/by-acreage/"),
            '<div class="scroll"><table class="data sortable"><thead><tr>'
            '<th scope="col">Acreage band</th><th scope="col" class="n">Active parcels</th>'
            '<th scope="col" class="n">Fixed OTC</th><th scope="col" class="n">Auction min bid</th>'
            '<th scope="col" class="n">Total acres</th><th scope="col" class="n">Median ticket</th>'
            '<th scope="col" class="n">Median $/acre</th><th scope="col" class="n">Lowest $/acre</th>'
            '</tr></thead><tbody>%s</tbody></table></div>' % rows,
            '<section class="callout"><h2>Why price per acre drops with tract size</h2>'
            '<p>Read our field guides on <a href="%s">how price per acre works</a> and <a href="%s">how big an acre really is</a>, or test parcel economics in the <a href="%s">Land Analyzer</a>.</p></section>' % (
                self.u("/research/price-per-acre/"), self.u("/research/acre-size/"), self.u("/analyze/")),
        ]
        desc = "Compare public-agency land prices, minimum bids, and price per acre across 6 acreage bands from under 0.25 acres to 50+ acres."
        return self.layout(
            "Land Prices by Acreage Band — Small Lots vs. Large Tracts | Landosaur",
            desc, "/land-prices/by-acreage/", "".join(body), indexable=True, jsonld=[crumb_ld], scripts=["tables.js"], wide=True,
        )

    def land_prices_methodology(self):
        m = self.market
        crumbs, crumb_ld = self.crumbs([("Land Prices", "/land-prices/"), ("Data & Methodology", "/land-prices/data-methodology/")])
        meth = (m.usda or {}).get("methodology", {})
        caveats = "".join("<li>%s</li>" % esc(c) for c in meth.get("caveats", []))
        body = [
            crumbs,
            '<h1>Land Price Data Methodology, Definitions &amp; Downloads</h1>',
            '<p class="lede">Landosaur separates three distinct data layers and never blends them into a synthetic score: (1) USDA NASS annual agricultural benchmarks, (2) 3,115 county-level USDA/FHFA benchmarks, and (3) live official public-agency offerings.</p>',
            self.land_prices_nav("/land-prices/data-methodology/"),
            '<section><h2>1. USDA NASS Agricultural Land Values (%d–%d)</h2><p>%s</p><ul class="notes">%s</ul></section>' % (
                m.first_year, m.latest_year, esc(meth.get("description", "")), caveats),
            '<section><h2>2. County Land Benchmarks (3,115 U.S. Counties)</h2>'
            '<p>County-level per-acre values come from the <a href="%s/" rel="nofollow noopener noreferrer">US County Land Index</a>, which publishes USDA Census/NASS agricultural estimates and FHFA residential land estimates by county. Each row labels its measure and vintage explicitly.</p></section>' % esc(config.LAND_INDEX_URL),
            '<section><h2>3. Live Official Public-Agency Feeds</h2>'
            '<p>Active listing counts, median ticket prices, and implied prices per acre are computed deterministically from verified official agencies read daily (<a href="%s">Sources &amp; read health</a>). Missing prices and missing acreages are never imputed.</p>'
            '<p><a href="%s">Download listings.csv</a> · <a href="%s">map.json</a> · <a href="%s">sources.json</a></p></section>' % (
                self.u("/sources/"), self.u("/data/listings.csv"), self.u("/data/map.json"), self.u("/data/sources.json")),
        ]
        desc = "How Landosaur sources, separates, and computes USDA NASS land values, 3,115 county benchmarks, and live public-agency offering statistics."
        return self.layout(
            "Land Price Data Methodology & Sources | Landosaur",
            desc, "/land-prices/data-methodology/", "".join(body), indexable=True, jsonld=[crumb_ld],
        )

    def land_prices_state(self, st):
        m = self.market
        y = m.latest_year
        name = st["name"]
        vals = st["values"]
        us = st["us_values"]
        crumbs, crumb_ld = self.crumbs([("Land Prices", "/land-prices/"), (name, st["path"])])
        faqs = m.state_faqs(st)

        # Direct answer + KPIs
        if st["published"] and vals.get("farm_real_estate") is not None:
            fre = vals["farm_real_estate"]
            answer = (
                '<p class="callout"><strong>%d %s benchmark:</strong> USDA NASS reports an average farm real estate value of '
                '<strong>%s per acre</strong> in %s (cropland %s/ac; pasture %s/ac). At that benchmark, 10 acres equate to %s and 20 acres to %s—though '
                'buildable lots, wooded recreation tracts, and tax-sale parcels can differ dramatically by county, road access, and utilities.</p>' % (
                    y, esc(name), esc(market_mod.usd(fre)), esc(name),
                    esc(market_mod.usd(vals.get("cropland"))), esc(market_mod.usd(vals.get("pasture"))),
                    esc(market_mod.usd(fre * 10)), esc(market_mod.usd(fre * 20)),
                )
            )
            kpis = (
                '<div class="kpi-grid">'
                '<div class="kpi-card"><span>Farm Real Estate (%d)</span><strong>%s/ac</strong><small>Rank #%s of %d states (lowest first)</small></div>'
                '<div class="kpi-card"><span>Cropland (%d)</span><strong>%s/ac</strong><small>U.S. ref: %s/ac</small></div>'
                '<div class="kpi-card"><span>Pasture (%d)</span><strong>%s/ac</strong><small>U.S. ref: %s/ac</small></div>'
                '<div class="kpi-card"><span>%s–%s Change</span><strong>%s</strong><small>Nominal USDA farm real estate</small></div>'
                '</div>' % (
                    y, esc(market_mod.usd(fre)), st["rank"] or "–", st["ranked_total"],
                    y, esc(market_mod.usd(vals.get("cropland"))), esc(market_mod.usd(us.get("cropland"))),
                    y, esc(market_mod.usd(vals.get("pasture"))), esc(market_mod.usd(us.get("pasture"))),
                    st["change_start"] or m.first_year, st["change_end"] or y, esc(market_mod.pct(st["change_pct"])),
                )
            )
            chart_html = '<section><h2>%s land values over time (%d–%d)</h2>%s</section>' % (
                esc(name), m.first_year, y, m.svg_trend_chart(st["code"], "%s agricultural land values per acre, %d to %d" % (name, m.first_year, y)))
            comp_rows = []
            for metric in m.metrics:
                sv, uv = vals.get(metric["id"]), us.get(metric["id"])
                diff = ((sv / float(uv) - 1.0) * 100.0) if (sv is not None and uv) else None
                comp_rows.append(
                    '<tr><th scope="row">%s</th><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
                        esc(metric["label"]), esc(market_mod.usd(sv)), esc(market_mod.usd(uv)), esc(market_mod.pct(diff)),
                    )
                )
            comp_html = (
                '<section><h2>%s vs. U.S. national benchmark (%d)</h2>'
                '<div class="scroll"><table class="data"><thead><tr><th>Measure</th><th class="n">%s</th>'
                '<th class="n">United States</th><th class="n">Difference</th></tr></thead><tbody>%s</tbody></table></div></section>' % (
                    esc(name), y, esc(name), "".join(comp_rows))
            )
        else:
            answer = (
                '<p class="callout"><strong>Note on %s USDA data:</strong> USDA NASS excludes %s from its annual contiguous-48 agricultural land value series. '
                'Landosaur never invents missing state averages; use the %d county benchmarks and live official agency listings below.</p>' % (
                    esc(name), esc(name), st["county_count"])
            )
            kpis = (
                '<div class="kpi-grid">'
                '<div class="kpi-card"><span>Counties Benchmarked</span><strong>%d</strong><small>US County Land Index</small></div>'
                '<div class="kpi-card"><span>County Median</span><strong>%s/ac</strong><small>USDA / FHFA county series</small></div>'
                '<div class="kpi-card"><span>Live Official Listings</span><strong>%s</strong><small>Tracked on Landosaur</small></div>'
                '<div class="kpi-card"><span>Lowest Live $/Acre</span><strong>%s</strong><small>Where price &amp; acres published</small></div>'
                '</div>' % (
                    st["county_count"], esc(market_mod.usd(st["county_median"])),
                    "{:,}".format(st["active_count"]),
                    esc(money(st["min_ppa"]) + "/ac") if st["min_ppa"] else "–",
                )
            )
            chart_html = ""
            comp_html = ""

        # County-by-county table (ALL counties in that state from 3,115-county dataset!)
        county_section = ""
        if st["counties"]:
            crows = "".join(
                '<tr><th scope="row">%s</th><td class="n" data-v="%s">%s/ac</td><td>%s</td>'
                '<td><a href="%s%s" rel="nofollow noopener noreferrer">County detail ↗</a></td></tr>' % (
                    esc(c["name"]), c["value"] or "", esc(market_mod.usd(c["value"])),
                    esc(c["kind_label"]), esc(config.LAND_INDEX_URL), esc(c["path"]),
                )
                for c in st["counties"]
            )
            county_section = (
                '<section><h2>%s land values per acre by county (%d counties)</h2>'
                '<p class="small">Sorted lowest to highest per acre. Click column headings to re-sort. Lowest: <strong>%s</strong> (%s/ac) · Median: <strong>%s/ac</strong> · Highest: <strong>%s</strong> (%s/ac).</p>'
                '<div class="scroll"><table class="data sortable"><thead><tr>'
                '<th scope="col">County</th><th scope="col" class="n">Benchmark $/acre</th>'
                '<th scope="col">Source &amp; measure</th><th scope="col">Reference</th>'
                '</tr></thead><tbody>%s</tbody></table></div></section>' % (
                    esc(name), st["county_count"],
                    esc(st["county_min"]["name"]) if st["county_min"] else "–",
                    esc(market_mod.usd(st["county_min"]["value"])) if st["county_min"] else "–",
                    esc(market_mod.usd(st["county_median"])),
                    esc(st["county_max"]["name"]) if st["county_max"] else "–",
                    esc(market_mod.usd(st["county_max"]["value"])) if st["county_max"] else "–",
                    crows,
                )
            )

        # Live Landosaur listings in this state (or honest empty state)
        if st["active_count"] > 0:
            priced = sorted(
                [r for r in st["active_listings"] if r.get("price") is not None],
                key=lambda r: ((r["price"] / r["acres"]) if r.get("acres") else 1e12, r["price"]),
            )
            sample = priced[:25] if priced else st["active_listings"][:25]
            inv_section = (
                '<section><h2>Live official government &amp; auction land in %s (%s active)</h2>'
                '<p><a class="button" href="%s">Open interactive %s land map (%s listings)</a></p>%s</section>' % (
                    esc(name), "{:,}".format(st["active_count"]),
                    self.u(st["browse_path"]), esc(name), "{:,}".format(st["active_count"]),
                    self.rows(sample, False, True),
                )
            )
        else:
            portal = self.state_portals.get(st["code"])
            portal_html = (
                ' Official state agency portal: <a href="%s" target="_blank" rel="noopener noreferrer"><strong>%s ↗</strong></a>.'
                % (esc(portal["url"]), esc(portal["agency"]))
            ) if portal else ""
            inv_section = (
                '<section class="callout"><h2>Finding or selling land in %s?</h2>'
                '<p>Landosaur does not yet ingest an automated open-data feed for %s (we show 0 automated agency listings honestly rather than scraping unverified ads).%s '
                'Have land for sale in %s? <a href="%s"><strong>List it free in 60 seconds (or via your AI Agent) →</strong></a> — or screen any %s parcel with our free '
                '<a href="%s"><strong>9-Agency Parcel X-Ray</strong></a> and <a href="%s"><strong>Land Analyzer</strong></a>.</p></section>' % (
                    esc(name), esc(name), portal_html, esc(name), self.u("/list/"), esc(name), self.u("/xray/"), self.u("/analyze/"))
            )

        body = [
            crumbs,
            '<div class="eyebrow">%s · %d Land Price Reference</div>' % (esc(name), y),
            '<h1>%s Land Prices Per Acre (%d): State History &amp; County Values</h1>' % (esc(name), y),
            self.land_prices_nav(st["path"]),
            answer, kpis, chart_html, comp_html, county_section, inv_section,
            self.faq_block(faqs, heading="Frequently asked questions about %s land prices" % name, section_id="state-faq"),
        ]
        fre_txt = "%s/acre farm real estate" % market_mod.usd(vals.get("farm_real_estate")) if vals.get("farm_real_estate") else "%d county benchmarks" % st["county_count"]
        desc = "%s land prices per acre in %d: %s, cropland & pasture history (%d-%d), all %d county values, and official land-buying tools." % (
            name, y, fre_txt, m.first_year, y, st["county_count"])
        ld = [{"@context": "https://schema.org", "@graph": [
            self.org_node(),
            {k: v for k, v in crumb_ld.items() if k != "@context"},
            {
                "@type": "Dataset", "@id": self.absu(st["path"] + "#dataset"),
                "name": "%s Land Prices Per Acre (%d-%d)" % (name, m.first_year, y),
                "description": desc, "url": self.absu(st["path"]), "isAccessibleForFree": True,
                "creator": {"@id": self.absu("/#organization")}, "spatialCoverage": name + ", United States",
                "temporalCoverage": "%d/%d" % (m.first_year, y),
            },
            self.faq_jsonld(faqs, st["path"] + "#faq"),
        ]}]
        return self.layout(
            "%s Land Prices Per Acre (%d) — County Values & History | Landosaur" % (name, y),
            desc, st["path"], "".join(body), indexable=True, jsonld=ld, scripts=["tables.js"], wide=True,
        )

    # ------------------------------------------------------------------ /analyze/ workbench
    def analyze_page(self):
        crumbs, crumb_ld = self.crumbs([("Land Analyzer", "/analyze/")])
        gates = (
            ("identity", "1. Parcel boundaries & offered rights (fee simple vs. lien/split estate)"),
            ("access", "2. Recorded legal & year-round physical road access"),
            ("use", "3. Zoning, legal-lot status & septic/well/buildability"),
            ("costs", "4. Material site-work, driveway, clearing & utility quotes"),
            ("availability", "5. Verified seller authority, clean title & liens"),
            ("value", "6. Exit value supported by reviewed closed comparable sales"),
        )
        gate_rows = "".join(
            '<label><span>%s</span><select data-gate="%s">'
            '<option value="unknown">Not yet verified</option>'
            '<option value="verified">Verified with evidence</option>'
            '<option value="failed">Critical issue found</option></select></label>' % (esc(lbl), gid)
            for gid, lbl in gates
        )
        body = [
            crumbs,
            '<div class="eyebrow">Free Client-Side Workbench · Zero Accounts</div>',
            '<h1>Land Deal, Financing, Electricity &amp; Valuation Analyzer</h1>',
            '<p class="lede">Price the full cost of buying and making raw land usable—including land loans with balloons, grid power extension vs. off-grid solar, verified closed comparable sales, 6 diligence gates, income cap-rate, and subdivision residual budgets. Everything runs in your browser with zero invented assumptions.</p>',
            '<div id="analyzer-parcel-banner" class="callout" hidden><p style="margin:0">Analyzing parcel: <strong></strong> · <a href="#">Back to parcel dossier →</a></p></div>',
            '<div id="analyzer-app">',
            '<div class="tab-bar" role="tablist" aria-label="Analyzer modules">'
            '<button type="button" role="tab" aria-selected="true" aria-controls="tab-cost">1. All-In Cost &amp; Financing</button>'
            '<button type="button" role="tab" aria-selected="false" aria-controls="tab-power">2. Power: Grid vs. Off-Grid</button>'
            '<button type="button" role="tab" aria-selected="false" aria-controls="tab-comps">3. Closed Comps Envelope</button>'
            '<button type="button" role="tab" aria-selected="false" aria-controls="tab-gates">4. 6-Gate, Income &amp; Residual</button>'
            '</div>',

            # TAB 1: Cost & Financing
            '<section id="tab-cost" role="tabpanel">'
            '<h2>All-in acquisition, site work &amp; land financing</h2>'
            '<form id="form-cost" class="worksheet" onsubmit="return false">'
            '<label><span>Purchase price or max bid</span><span class="in"><input name="price" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Parcel size</span><span class="in"><input name="acres" type="number" min="0" step="any" placeholder="0"><i>acres</i></span></label>'
            '<label><span>Closing costs &amp; buyer premium</span><span class="in"><input name="closingPct" type="number" min="0" max="100" step="any" placeholder="3"><i>%</i></span></label>'
            '<label><span>Survey, title &amp; diligence</span><span class="in"><input name="diligence" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Driveway / road length</span><span class="in"><input name="roadFt" type="number" min="0" step="any" placeholder="0"><i>ft</i></span></label>'
            '<label><span>Road build cost per foot</span><span class="in"><input name="roadRate" type="number" min="0" step="any" placeholder="0"><i>$/ft</i></span></label>'
            '<label><span>Power, well &amp; septic</span><span class="in"><input name="utilities" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Clearing, grading &amp; site work</span><span class="in"><input name="siteWork" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Works contingency reserve</span><span class="in"><input name="contingencyPct" type="number" min="0" max="100" step="any" placeholder="15"><i>%</i></span></label>'
            '<label><span>Annual property taxes</span><span class="in"><input name="annualTax" type="number" min="0" step="any" placeholder="0"><i>$/yr</i></span></label>'
            '<label><span>Monthly insurance / HOA / upkeep</span><span class="in"><input name="monthlyOther" type="number" min="0" step="any" placeholder="0"><i>$/mo</i></span></label>'
            '<label><span>Expected hold period</span><span class="in"><input name="holdMonths" type="number" min="0" max="600" step="1" value="24"><i>mos</i></span></label>'
            '<label><span>Estimated future selling cost</span><span class="in"><input name="sellPct" type="number" min="0" max="99" step="any" value="8"><i>%</i></span></label>'
            '<label class="inline-chk" style="grid-column:1/-1;padding-top:6px"><input name="useFin" type="checkbox"> Include land loan or seller financing (with optional balloon)</label>'
            '<div id="fin-fields" hidden style="grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px 14px;padding-top:6px;border-top:1px solid var(--line)">'
            '<label><span>Down payment</span><span class="in"><input name="downPayment" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Annual interest rate (APR)</span><span class="in"><input name="apr" type="number" min="0" max="100" step="any" placeholder="8.5"><i>%</i></span></label>'
            '<label><span>Amortization schedule</span><span class="in"><input name="amortMonths" type="number" min="1" max="600" step="1" value="120"><i>mos</i></span></label>'
            '<label><span>Balloon due (0 = none)</span><span class="in"><input name="balloonMonths" type="number" min="0" max="600" step="1" value="0"><i>mos</i></span></label>'
            '<label><span>Loan origination fee</span><span class="in"><input name="origPct" type="number" min="0" max="100" step="any" placeholder="1"><i>%</i></span></label>'
            '</div></form>'
            '<div class="kpi-grid">'
            '<div class="kpi-card"><span>Unlevered All-In Cost</span><strong id="out-unlevered">–</strong><small>Closing: <span id="out-closing">–</span> · Works: <span id="out-works">–</span> · Hold: <span id="out-holding">–</span></small></div>'
            '<div class="kpi-card"><span>Total Economic Cost</span><strong id="out-econ">–</strong><small id="out-ppa">Enter acres &amp; price</small></div>'
            '<div class="kpi-card"><span>Cash Required Through Hold</span><strong id="out-cash-req">–</strong><small><span id="out-monthly">Cash purchase</span> · <span id="out-balloon">–</span></small></div>'
            '<div class="kpi-card"><span>Break-Even Gross Sale</span><strong id="out-breakeven">–</strong><small>After entered selling cost %</small></div>'
            '</div>'
            '<p><button type="button" id="copy-analysis" class="button ghost">Copy shareable link to these numbers</button></p>'
            '</section>',

            # TAB 2: Power / Electricity
            '<section id="tab-power" role="tabpanel" hidden>'
            '<h2>Electricity feasibility: Utility Grid Extension vs. Off-Grid Solar</h2>'
            '<p class="small">Power is often the single biggest hidden cost on raw land. Compare real utility line-extension quotes against an off-grid solar + LiFePO4 battery + backup generator system over your ownership horizon.</p>'
            '<p id="pwr-solar-hint" class="callout" hidden style="margin-bottom:12px"></p>'
            '<form id="form-power" class="worksheet" onsubmit="return false">'
            '<label><span>Comparison horizon</span><span class="in"><input name="horizonYears" type="number" min="1" max="50" step="1" value="10"><i>yrs</i></span></label>'
            '<label><span>Distance to distribution line</span><span class="in"><input name="distFt" type="number" min="0" step="any" placeholder="0"><i>ft</i></span></label>'
            '<label><span>Utility line extension rate</span><span class="in"><input name="perFt" type="number" min="0" step="any" placeholder="0"><i>$/ft</i></span></label>'
            '<label><span>Transformer, pole &amp; meter drop</span><span class="in"><input name="transformer" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Easement, clearing &amp; trenching</span><span class="in"><input name="easement" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Monthly utility base charge</span><span class="in"><input name="baseCharge" type="number" min="0" step="any" placeholder="0"><i>$/mo</i></span></label>'
            '<label><span>Expected monthly usage</span><span class="in"><input name="kwhMonth" type="number" min="0" step="any" placeholder="0"><i>kWh</i></span></label>'
            '<label><span>Utility electricity rate</span><span class="in"><input name="kwhRate" type="number" min="0" step="any" placeholder="0.16"><i>$/kWh</i></span></label>'
            '<label><span>Off-grid solar array &amp; inverter</span><span class="in"><input name="solarArray" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Off-grid battery bank</span><span class="in"><input name="battery" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Backup generator &amp; transfer</span><span class="in"><input name="generator" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Battery replacement reserve</span><span class="in"><input name="batteryReplace" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Annual generator fuel</span><span class="in"><input name="fuelAnnual" type="number" min="0" step="any" placeholder="0"><i>$/yr</i></span></label>'
            '<label><span>Annual off-grid maintenance</span><span class="in"><input name="maintAnnual" type="number" min="0" step="any" placeholder="0"><i>$/yr</i></span></label>'
            '</form>'
            '<div class="kpi-grid">'
            '<div class="kpi-card"><span>Grid Extension Capex</span><strong id="pwr-grid-capex">–</strong><small>Upfront line, transformer &amp; trench</small></div>'
            '<div class="kpi-card"><span>Grid Total (Horizon)</span><strong id="pwr-grid-total">–</strong><small id="pwr-grid-yr">–</small></div>'
            '<div class="kpi-card"><span>Off-Grid System Capex</span><strong id="pwr-off-capex">–</strong><small>Solar, inverter, battery &amp; generator</small></div>'
            '<div class="kpi-card"><span>Off-Grid Total (Horizon)</span><strong id="pwr-off-total">–</strong><small id="pwr-off-yr">–</small></div>'
            '</div>'
            '<p id="pwr-verdict" class="callout"></p>'
            '</section>',

            # TAB 3: Comparable Closed Sales
            '<section id="tab-comps" role="tabpanel" hidden>'
            '<h2>Verified closed comparable-sales envelope</h2>'
            '<p class="small">Enter at least 3 verified closed arm\'s-length sales within 0.5×–2× your subject acreage, each with a public recorder/listing URL. Nonzero adjustments require an explicit reason.</p>'
            '<div class="worksheet" style="margin-bottom:12px">'
            '<label><span>Subject parcel acreage</span><span class="in"><input id="comp-subject-acres" type="number" min="0" step="any" placeholder="e.g. 10"><i>acres</i></span></label>'
            '</div>'
            '<div class="scroll"><table class="data comp-table"><thead><tr>'
            '<th>Source / Recorder URL</th><th>Closed Price ($)</th><th>Acres</th><th>Sale Date</th>'
            '<th>Adj (%)</th><th>Adjustment Reason</th><th>Status</th><th></th></tr></thead>'
            '<tbody id="comp-rows"></tbody></table></div>'
            '<p><button type="button" id="add-comp" class="button ghost sm">+ Add comparable sale</button></p>'
            '<div id="comp-summary"></div>'
            '</section>',

            # TAB 4: 6-Gate Diligence, Income & Residual
            '<section id="tab-gates" role="tabpanel" hidden>'
            '<h2>6-Gate Diligence &amp; Exit Return Check</h2>'
            '<form id="form-gates" class="worksheet" onsubmit="return false">'
            '<label><span>Expected future exit value</span><span class="in"><input name="exitValue" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Exit selling cost</span><span class="in"><input name="exitSellPct" type="number" min="0" max="99" step="any" value="8"><i>%</i></span></label>'
            '<label><span>Annual discount rate</span><span class="in"><input name="discountPct" type="number" min="0" max="100" step="any" value="10"><i>%</i></span></label>'
            '__GATE_ROWS__</form>'
            '<div class="kpi-grid">'
            '<div class="kpi-card"><span>Diligence Verdict</span><strong id="gate-status" style="font-size:17px">Enter figures</strong><small>All 6 gates must be verified</small></div>'
            '<div class="kpi-card"><span>Net Exit Proceeds</span><strong id="gate-net-exit">–</strong><small>After exit selling costs</small></div>'
            '<div class="kpi-card"><span>Unlevered Surplus</span><strong id="gate-surplus">–</strong><small>Net exit minus all-in cost</small></div>'
            '<div class="kpi-card"><span>Discounted Surplus</span><strong id="gate-npv">–</strong><small>Simplified time-value check</small></div>'
            '</div>'
            '<div class="research-split" style="margin-top:24px">'
            '<div><h3>Income / Lease Cap-Rate Valuation</h3>'
            '<form id="form-income" class="worksheet" onsubmit="return false">'
            '<label><span>Annual gross rent (farm/hunting/solar)</span><span class="in"><input name="grossRent" type="number" min="0" step="any" placeholder="0"><i>$/yr</i></span></label>'
            '<label><span>Vacancy / collection loss</span><span class="in"><input name="vacancyPct" type="number" min="0" max="100" step="any" value="5"><i>%</i></span></label>'
            '<label><span>Annual operating expenses &amp; tax</span><span class="in"><input name="opCost" type="number" min="0" step="any" placeholder="0"><i>$/yr</i></span></label>'
            '<label><span>Annual capital reserve</span><span class="in"><input name="reserve" type="number" min="0" step="any" placeholder="0"><i>$/yr</i></span></label>'
            '<label><span>Target cap rate</span><span class="in"><input name="capRate" type="number" min="0.1" max="100" step="any" value="6"><i>%</i></span></label>'
            '</form><dl class="kv totals"><dt>Net Operating Income</dt><dd id="inc-noi">–</dd><dt>Indicated Income Value</dt><dd id="inc-val">–</dd></dl></div>'
            '<div><h3>Subdivision / Development Residual Budget</h3>'
            '<form id="form-residual" class="worksheet" onsubmit="return false">'
            '<label><span>Saleable lots / units</span><span class="in"><input name="units" type="number" min="1" step="1" placeholder="4"><i>lots</i></span></label>'
            '<label><span>Expected sale price per lot</span><span class="in"><input name="pricePerUnit" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Months to sellout</span><span class="in"><input name="monthsToSale" type="number" min="0" max="600" step="1" value="18"><i>mos</i></span></label>'
            '<label><span>Hard / engineering / platting costs</span><span class="in"><input name="hard" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Soft / legal / permitting costs</span><span class="in"><input name="soft" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Road &amp; utility infrastructure</span><span class="in"><input name="infra" type="number" min="0" step="any" placeholder="0"><i>$</i></span></label>'
            '<label><span>Cost contingency</span><span class="in"><input name="resCont" type="number" min="0" max="100" step="any" value="15"><i>%</i></span></label>'
            '<label><span>Developer margin</span><span class="in"><input name="resProfit" type="number" min="0" max="100" step="any" value="20"><i>%</i></span></label>'
            '<label><span>Selling costs</span><span class="in"><input name="resSell" type="number" min="0" max="100" step="any" value="8"><i>%</i></span></label>'
            '<label><span>Annual discount rate</span><span class="in"><input name="resDiscount" type="number" min="0" max="100" step="any" value="10"><i>%</i></span></label>'
            '</form><dl class="kv totals"><dt>Gross Sellout</dt><dd id="res-gross">–</dd><dt>Residual Land Budget</dt><dd id="res-budget">–</dd></dl></div>'
            '</div></section>',
            '</div>',
        ]
        body[-2] = body[-2].replace("__GATE_ROWS__", gate_rows)
        desc = "Free land deal analyzer: calculate all-in acquisition & land loan/balloon costs, compare utility power extension vs. off-grid solar, verify closed comps, and screen subdivision residual budgets."
        ld = [{"@context": "https://schema.org", "@graph": [
            self.org_node(),
            {k: v for k, v in crumb_ld.items() if k != "@context"},
            {
                "@type": "SoftwareApplication", "@id": self.absu("/analyze/#app"),
                "name": "Landosaur Land Deal, Electricity & Valuation Analyzer",
                "applicationCategory": "FinanceApplication", "operatingSystem": "Web",
                "url": self.absu("/analyze/"), "description": desc, "isAccessibleForFree": True,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "publisher": {"@id": self.absu("/#organization")},
            },
        ]}]
        return self.layout(
            "Land Valuation, Financing & Off-Grid Power Analyzer | Landosaur",
            desc, "/analyze/", "".join(body), indexable=True, jsonld=ld, scripts=["analyze.js"], wide=True,
        )

    # ------------------------------------------------------------------ research (benchmarks + 29 guides library)
    def research(self):
        b = self.benchmarks
        crumbs, crumb_ld = self.crumbs([("Research & Guides", "/research/")])

        findings_html = "".join(
            '<li class="finding-card" id="%s"><div class="finding-head"><span>%02d · %s</span><strong>%s</strong></div><p>%s</p></li>'
            % (esc(f["id"]), i + 1, esc(f["label"]), esc(f["metric"]), esc(f["sentence"]))
            for i, f in enumerate(b["findings"])
        )
        state_rows = "".join(
            '<tr><th scope="row"><a href="%s">%s</a></th><td class="n">%s</td><td class="n">%d</td>'
            '<td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
            % (
                self.u(st["path"]), esc(st["name"]), "{:,}".format(st["active_count"]), st["county_count"],
                esc(research.fmt_acres(st["total_acres"])) if st["acres_count"] else "–",
                "{:,}".format(st["priced_count"]),
                esc(research.fmt_money_exact(st["median_price"], "–")),
                esc(research.fmt_money_exact(st["median_ppa"], "–")),
                esc(research.fmt_money_exact(st["mean_ppa"], "–")),
            )
            for st in b["states"]
        )
        agency_rows = "".join(
            '<tr><th scope="row"><a href="%s" rel="noopener">%s</a><span class="sub">%s</span></th>'
            '<td>%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
            % (
                esc(ag["url"]), esc(ag["agency"]), esc(ag["about"]),
                esc(ag["state_name"]), esc(ag["pricing_summary"]),
                "{:,}".format(ag["active_count"]),
                esc(research.fmt_acres(ag["total_acres"])) if ag["acres_count"] else "–",
                esc(research.fmt_money_exact(ag["median_price"], "–")),
                esc(research.fmt_money_exact(ag["median_ppa"], "–")),
            )
            for ag in b["agencies"]
        )
        county_rows = "".join(
            '<tr><td class="n">%d</td><th scope="row"><a href="%s">%s</a>, %s</th><td class="n">%s</td>'
            '<td class="n">%.1f%%</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
            % (
                idx + 1, self.u(c["path"]), esc(c["name"]), esc(c["state_code"]),
                "{:,}".format(c["active_count"]), c["share_pct"],
                esc(research.fmt_acres(c["total_acres"])) if c["acres_count"] else "–",
                "{:,}".format(c["priced_count"]),
                esc(research.fmt_money_exact(c["median_price"], "–")),
            )
            for idx, c in enumerate(b["top_counties"])
        )
        price_bracket_rows = "".join(
            '<tr><th scope="row">%s</th><td class="n">%s</td><td class="n">%.1f%%</td></tr>'
            % (esc(row["label"]), "{:,}".format(row["count"]), row["pct"])
            for row in b["price_brackets"]
        )
        acreage_bracket_rows = "".join(
            '<tr><th scope="row">%s</th><td class="n">%s</td><td class="n">%.1f%%</td><td class="n">%s</td><td class="n">%.1f%%</td></tr>'
            % (esc(row["label"]), "{:,}".format(row["count"]), row["pct"], esc(research.fmt_acres(row["acres"])), row["acres_pct"])
            for row in b["acreage_brackets"]
        )

        # Categorized 29-guide Field Library
        by_cat = {}
        for g in self.guides:
            by_cat.setdefault(g["category"], []).append(g)
        guide_sections = []
        for cat_name, items in by_cat.items():
            cards = "".join(
                '<article class="info-card"><div class="eyebrow">%s</div>'
                '<h3><a href="%s">%s</a></h3><p>%s</p>'
                '<a class="card-link" href="%s">Read guide →</a></article>' % (
                    esc(cat_name), self.u(g["path"]), esc(g["title"]), esc(g["description"]), self.u(g["path"]))
                for g in items
            )
            guide_sections.append('<h3 style="margin-top:22px">%s</h3><div class="card-grid">%s</div>' % (esc(cat_name), cards))

        kpi_ppa = esc(research.fmt_money_exact(b["median_ppa"], "N/A"))
        kpi_ppa_sub = "Mean %s · n = %s with price &amp; acres" % (
            esc(research.fmt_money_exact(b["mean_ppa"], "N/A")), "{:,}".format(b["both_count"]))

        body = [
            crumbs,
            '<h1>US Public-Agency Land Research, Benchmarks &amp; Buyer Guides</h1>',
            '<p class="lede">Original benchmarks computed deterministically from <strong>%s</strong> active public-agency land offerings '
            'across %d U.S. %s and %d official agencies (snapshot verified <strong>%s</strong>), paired with %d source-cited land due-diligence guides.</p>' % (
                "{:,}".format(b["active_count"]), b["state_count"], "state" if b["state_count"] == 1 else "states",
                b["agency_count"], esc(b["updated"]), len(self.guides)),
            '<div class="kpi-grid" aria-label="Headline public land statistics">'
            '<div class="kpi-card"><span>Active Offerings</span><strong>%s</strong><small>%d %s · %d agencies · %s</small></div>'
            '<div class="kpi-card"><span>Published Acreage</span><strong>%s ac</strong><small>Across %s listings reporting area</small></div>'
            '<div class="kpi-card"><span>Median Price / Acre</span><strong>%s</strong><small>%s</small></div>'
            '<div class="kpi-card"><span>Median Published Price</span><strong>%s</strong><small>Across %s priced or min-bid listings</small></div>'
            '</div>' % (
                "{:,}".format(b["active_count"]), b["state_count"], "state" if b["state_count"] == 1 else "states",
                b["agency_count"], esc(b["updated"]),
                esc(research.fmt_acres(b["total_acres"])), "{:,}".format(b["acres_reported_count"]),
                kpi_ppa, kpi_ppa_sub,
                esc(research.fmt_money_exact(b["median_price"], "N/A")), "{:,}".format(b["priced_count"]),
            ),
            '<nav class="research-jumps" aria-label="Research sections">'
            '<a href="#field-guides">29 Buyer Guides</a>'
            '<a href="#key-findings">Key Findings</a>'
            '<a href="#state-benchmarks">By State</a>'
            '<a href="#agency-breakdown">By Agency</a>'
            '<a href="#top-counties">Top 10 Counties</a>'
            '<a href="#distributions">Distributions</a>'
            '<a href="#methodology">Methodology</a>'
            '<a href="#research-faq">FAQ</a>'
            '</nav>',
            '<section id="field-guides"><h2>Land Buyer\'s Field Library (%d Source-Cited Guides)</h2>'
            '<p class="small">Practical, agency-cited diligence guides covering tax sales, wetlands, wells, septic, mineral rights, zoning, surveys, financing, and rural land uses.</p>%s</section>' % (
                len(self.guides), "".join(guide_sections)),
            '<section id="key-findings"><h2>Key citable findings (snapshot %s)</h2>'
            '<p class="small">Standalone, source-attributed statistics computed directly from the active official agency catalog.</p>'
            '<ol class="finding-grid">%s</ol></section>' % (esc(b["updated"]), findings_html),
            '<section id="state-benchmarks"><h2>State-by-state price &amp; acreage benchmarks</h2>'
            '<div class="scroll"><table class="data sortable"><thead><tr>'
            '<th scope="col">State</th><th scope="col" class="n">Active listings</th><th scope="col" class="n">Counties</th>'
            '<th scope="col" class="n">Published acres</th><th scope="col" class="n">Priced / bid</th>'
            '<th scope="col" class="n">Median price / bid</th><th scope="col" class="n">Median $/acre</th><th scope="col" class="n">Mean $/acre</th>'
            '</tr></thead><tbody>%s</tbody></table></div></section>' % state_rows,
            '<section id="agency-breakdown"><h2>Breakdown by official public agency</h2>'
            '<div class="scroll"><table class="data sortable"><thead><tr>'
            '<th scope="col">Official agency</th><th scope="col">State</th><th scope="col">Pricing type</th>'
            '<th scope="col" class="n">Active</th><th scope="col" class="n">Published acres</th>'
            '<th scope="col" class="n">Median price / bid</th><th scope="col" class="n">Median $/acre</th>'
            '</tr></thead><tbody>%s</tbody></table></div></section>' % agency_rows,
            '<section id="top-counties"><h2>Top 10 counties &amp; jurisdictions by active public listings</h2>'
            '<div class="scroll"><table class="data sortable"><thead><tr>'
            '<th scope="col" class="n">#</th><th scope="col">County / jurisdiction</th><th scope="col" class="n">Active</th>'
            '<th scope="col" class="n">Catalog share</th><th scope="col" class="n">Published acres</th>'
            '<th scope="col" class="n">Priced / bid</th><th scope="col" class="n">Median price / bid</th>'
            '</tr></thead><tbody>%s</tbody></table></div></section>' % county_rows,
            '<section id="distributions"><h2>Distribution across price &amp; acreage brackets</h2>'
            '<div class="research-split">'
            '<div><h3>Published price / minimum bid brackets (n = %s)</h3>'
            '<div class="scroll"><table class="data"><thead><tr><th scope="col">Price / bid bracket</th><th scope="col" class="n">Listings</th><th scope="col" class="n">Share</th></tr></thead>'
            '<tbody>%s</tbody></table></div></div>'
            '<div><h3>Published acreage brackets (n = %s)</h3>'
            '<div class="scroll"><table class="data"><thead><tr><th scope="col">Acreage bracket</th><th scope="col" class="n">Listings</th><th scope="col" class="n">Listing share</th><th scope="col" class="n">Total acres</th><th scope="col" class="n">Acreage share</th></tr></thead>'
            '<tbody>%s</tbody></table></div></div></div></section>' % (
                "{:,}".format(b["priced_count"]), price_bracket_rows,
                "{:,}".format(b["acres_reported_count"]), acreage_bracket_rows,
            ),
            '<section id="methodology" class="research-box"><h2>Methodology, data freshness &amp; limitations</h2>'
            '<dl class="kv">'
            '<dt>Snapshot date</dt><dd>%s (latest verified agency read; %s active offerings out of %s stored records).</dd>'
            '<dt>Zero imputation</dt><dd>Missing prices (%s offerings, %.1f%%) and missing parcel areas (%s offerings) are never guessed. Price-per-acre benchmarks strictly use the %s offerings reporting both positive price/min-bid and positive acreage.</dd>'
            '<dt>Open downloads</dt><dd><a href="%s">listings.csv</a> · <a href="%s">map.json</a> · <a href="%s">sources.json</a> · <a href="%s">Atom feed</a> · <a href="%s">50-State Land Prices</a></dd>'
            '</dl></section>' % (
                esc(b["updated"]), "{:,}".format(b["active_count"]), "{:,}".format(b["total_tracked"]),
                "{:,}".format(b["unpriced_count"]), b["price_kinds"]["none"]["pct"],
                "{:,}".format(b["acres_missing_count"]), "{:,}".format(b["both_count"]),
                self.u("/data/listings.csv"), self.u("/data/map.json"), self.u("/data/sources.json"),
                self.u("/feeds/new.xml"), self.u("/land-prices/"),
            ),
            self.faq_block(b["research_faqs"], heading="Frequently asked questions", intro="Direct answers computed from the %s public-agency snapshot." % esc(b["updated"]), section_id="research-faq"),
        ]
        desc = (
            "Original benchmarks from %s active U.S. government land offerings across %d states and %d public agencies (%s), "
            "plus %d source-cited land due-diligence guides covering tax sales, wetlands, septic, wells, access, and valuation."
        ) % ("{:,}".format(b["active_count"]), b["state_count"], b["agency_count"], b["updated"], len(self.guides))
        crumb_graph_node = {k: v for k, v in crumb_ld.items() if k != "@context"}
        crumb_graph_node["@id"] = self.absu("/research/#breadcrumb")
        ld = [{"@context": "https://schema.org", "@graph": [
            self.org_node(),
            crumb_graph_node,
            {
                "@type": "Article", "@id": self.absu("/research/#article"),
                "headline": "US Public-Agency Rural Land Price & Acreage Benchmarks",
                "description": desc, "url": self.absu("/research/"), "mainEntityOfPage": self.absu("/research/"),
                "inLanguage": "en", "datePublished": b["updated"], "dateModified": b["updated"],
                "author": {"@id": self.absu("/#organization")}, "publisher": {"@id": self.absu("/#organization")},
                "image": self.absu("/og/research.png"), "isBasedOn": {"@id": self.absu("/research/#dataset")},
            },
            {
                "@type": "Dataset", "@id": self.absu("/research/#dataset"),
                "name": "US Public-Agency Rural & Municipal Land Price and Acreage Benchmark Dataset",
                "description": desc, "url": self.absu("/research/"), "dateModified": b["updated"],
                "temporalCoverage": b["updated"], "spatialCoverage": ", ".join(st["name"] for st in b["states"]) or "United States",
                "isAccessibleForFree": True, "creator": {"@id": self.absu("/#organization")}, "publisher": {"@id": self.absu("/#organization")},
                "distribution": [
                    {"@type": "DataDownload", "name": "Landosaur Listings CSV", "encodingFormat": "text/csv", "contentUrl": self.absu("/data/listings.csv")},
                    {"@type": "DataDownload", "name": "Landosaur Map JSON", "encodingFormat": "application/json", "contentUrl": self.absu("/data/map.json")},
                    {"@type": "DataDownload", "name": "Landosaur Sources Status JSON", "encodingFormat": "application/json", "contentUrl": self.absu("/data/sources.json")},
                ],
            },
            self.faq_jsonld(b["research_faqs"], "/research/#faq"),
        ]}]
        return self.layout(
            "US Public-Agency Land Benchmarks & 29 Land Buying Guides | Landosaur",
            desc, "/research/", "".join(body), indexable=True, jsonld=ld, og="research", scripts=["tables.js"], wide=True,
        )

    def guide_page(self, g):
        crumbs, crumb_ld = self.crumbs([("Research & Guides", "/research/"), (g["title"], g["path"])])
        related = [x for x in self.guides if x["category"] == g["category"] and x["slug"] != g["slug"]][:4]
        src_html = ""
        if g["sources"]:
            lis = "".join('<li><a href="%s" rel="noopener noreferrer">%s</a></li>' % (esc(s["url"]), esc(s["title"])) for s in g["sources"])
            src_html = '<section><h2>Official &amp; Primary Sources</h2><ul class="notes">%s</ul></section>' % lis
        rel_html = ""
        if related:
            cards = "".join(
                '<article class="info-card"><h3><a href="%s">%s</a></h3><p>%s</p></article>' % (
                    self.u(x["path"]), esc(x["title"]), esc(x["description"]))
                for x in related
            )
            rel_html = '<section><h2>Related guides in %s</h2><div class="card-grid">%s</div></section>' % (esc(g["category"]), cards)
        body = [
            crumbs,
            '<div class="eyebrow">%s · Updated %s</div>' % (esc(g["category"]), esc(g["updated"])),
            '<h1>%s</h1>' % esc(g["title"]),
            '<p class="lede">%s</p>' % esc(g["description"]),
            '<article class="prose">%s</article>' % g["body_html"],
            src_html,
            '<section class="callout"><h2>Apply this to a real parcel</h2>'
            '<p>Model all-in acquisition, financing, and utility costs in the <a href="%s"><strong>Land Analyzer</strong></a>, check <a href="%s">50-State Land Prices</a>, or browse <a href="%s">live official land listings on the map</a>.</p></section>' % (
                self.u("/analyze/"), self.u("/land-prices/"), self.u("/")),
            rel_html,
        ]
        ld = [{"@context": "https://schema.org", "@graph": [
            self.org_node(),
            {k: v for k, v in crumb_ld.items() if k != "@context"},
            {
                "@type": "Article", "@id": self.absu(g["path"] + "#article"),
                "headline": g["title"], "description": g["description"],
                "url": self.absu(g["path"]), "mainEntityOfPage": self.absu(g["path"]),
                "datePublished": g["updated"], "dateModified": g["updated"],
                "author": {"@id": self.absu("/#organization")}, "publisher": {"@id": self.absu("/#organization")},
                "image": self.absu("/og/research.png"),
            },
        ]}]
        return self.layout(
            "%s | Landosaur Research" % g["title"],
            g["description"], g["path"], "".join(body), indexable=True, jsonld=ld, og="research",
        )

    # ------------------------------------------------------------------ listing dossier
    def listing(self, r):
        cat = self.cat
        st = cat.states[r["state"]]
        county = st["counties"][self._county_slug(r)]
        trail = [(st["name"], cat.state_path(st)), (county["name"], cat.county_path(st, county)), (r["title"], cat.listing_path(r))]
        crumbs, crumb_ld = self.crumbs(trail)
        src = cat.sources.get(r["source"], {})
        kv = [
            ("Status", self.badge(r)),
            ("Price", esc(price_line(r))),
            ("Acres", esc(acres_text(r["acres"]))),
        ]
        if r.get("price") and r.get("acres"):
            kv.append(("Implied $/acre", esc(money(r["price"] / r["acres"]) + " / acre")))
        kv.append(("Location", esc(", ".join(x for x in (r.get("address"), r.get("locality"), r["county_label"], r["state_name"]) if x))))
        if r.get("apn"):
            kv.append(("Parcel", esc(r["apn"])))
        if r.get("deadline"):
            kv.append(("Deadline", esc(r["deadline"][:16].replace("T", " ") + " UTC")))
        kv.append(("Source", '<a href="%s" rel="noopener">%s</a>' % (esc(src.get("url", r["url"])), esc(src.get("agency", r["source"])))))
        kv.append(("Last read", esc(r["checked"] or "unknown")))
        if r.get("first_seen"):
            kv.append(("First seen", esc(r["first_seen"])))

        facts = "".join(
            '<tr><th scope="row">%s</th><td>%s</td><td>%s%s</td></tr>' % (
                esc(NICE_TOPIC.get(f["topic"], f["topic"].replace("_", " ").capitalize())), esc(f["value"]),
                ('<a href="%s" rel="noopener">%s</a>' % (esc(adapters.expand_url(r, f["url"])), "source")) if f.get("url") else "",
                (' <span class="note">%s</span>' % esc(adapters.note_text(f["note"]))) if f.get("note") else "",
            )
            for f in r["facts"]
        )
        context = ""
        cv = cat.county_value(r)
        state_price_link = '/land-prices/%s/' % st["slug"]
        if cv and cv.get("value"):
            kind = {"c": "%d census" % cv["year"], "e": "%d estimate" % cv["year"], "i": "%d estimate" % cv["year"],
                    "r": "%d residential land, FHFA" % cv["year"]}.get(cv["kind"], str(cv["year"]))
            per = ""
            gauge = ""
            if r["price"] and r["acres"]:
                l_ppa = r["price"] / r["acres"]
                c_val = float(cv["value"])
                diff_pct = ((l_ppa / c_val) - 1.0) * 100.0
                diff_str = "%.0f%% %s county average" % (abs(diff_pct), "above" if diff_pct >= 0 else "below")
                max_bar = max(l_ppa, c_val, 1.0)
                w_list = max(4.0, min(100.0, (l_ppa / max_bar) * 100.0))
                w_cnty = max(4.0, min(100.0, (c_val / max_bar) * 100.0))
                per = " This listing's %s works out to <strong>%s per acre</strong> (%s)." % (
                    "minimum bid" if r["price_kind"] == "min_bid" else "price", esc(money(l_ppa)), esc(diff_str))
                gauge = (
                    '<div class="bench-gauge" aria-label="Listing price per acre compared to county benchmark">'
                    '<div class="bench-gauge-row"><strong>This listing (%s)</strong>'
                    '<div class="bench-track"><div class="bench-fill%s" style="width:%.1f%%"></div></div>'
                    '<span class="card-metric">%s/ac</span></div>'
                    '<div class="bench-gauge-row"><span>%s avg</span>'
                    '<div class="bench-track"><div class="bench-fill county" style="width:%.1f%%"></div></div>'
                    '<span class="card-metric">%s/ac</span></div>'
                    '<p class="small" style="margin:6px 0 0"><strong>%s.</strong> Small lots, auction opening floors, road access, utilities, and title defects cause wide swings vs. county averages—context only, not an appraisal.</p>'
                    '</div>'
                ) % (
                    "min bid" if r["price_kind"] == "min_bid" else "price",
                    " high" if diff_pct > 25 else "", w_list, esc(money(l_ppa)),
                    esc(cv["name"]), w_cnty, esc(money(c_val)), esc(diff_str.capitalize()),
                )
            what = "Land under single-family homes" if cv["kind"] == "r" else "Farm real estate"
            context = (
                '<section><h2>Land values in %s</h2>%s<p>%s in %s averaged <strong>%s per acre</strong> (%s) on the '
                '<a href="%s%s" rel="nofollow noopener noreferrer">US County Land Index</a>.%s County averages mix very different land; '
                'they are context, not an appraisal. <a href="%s">See %s land price history &amp; all counties →</a></p></section>'
            ) % (
                esc(r["county_label"]), gauge, what, esc(cv["name"] + ", " + r["state_name"]), money(cv["value"]), esc(kind),
                esc(config.LAND_INDEX_URL), esc(cv["path"]), per, self.u(state_price_link), esc(r["state_name"]),
            )

        zoning_val = next((f["value"] for f in r["facts"] if f["topic"] == "zoning"), "")
        buildable_val = next((f["value"] for f in r["facts"] if f["topic"] == "buildable_lot"), "")
        side_lot_val = next((f["value"] for f in r["facts"] if f["topic"] == "side_lot_eligible"), "")
        parcel = {
            "slug": r["id"], "lat": r.get("lat"), "lon": r.get("lon"), "geometry": r.get("geometry"), "title": r["title"],
            "acres": r.get("acres"), "price": r.get("price"), "price_kind": r.get("price_kind"),
            "offering": r.get("offering"), "zoning": zoning_val, "buildable": buildable_val, "side_lot": side_lot_val,
        }
        xray_section = ""
        if r.get("lat") is not None and r.get("lon") is not None:
            la, lo = r["lat"], r["lon"]
            diligence_links = (
                '<div class="diligence-bar" aria-label="Parcel GIS due-diligence tools">'
                '<button type="button" id="measure-toggle" class="chip-btn">Measure distance</button>'
                '<button type="button" id="export-kml" class="chip-btn">Download KML</button>'
                '<button type="button" id="export-gpx" class="chip-btn">Download GPX</button>'
                '<a href="https://www.google.com/maps/@%.6f,%.6f,17z/data=!3m1!1e3" target="_blank" rel="noopener noreferrer">Satellite ↗</a>'
                '<a href="https://msc.fema.gov/portal/search?AddressQuery=%.6f%%2C%.6f" target="_blank" rel="noopener noreferrer">FEMA Map ↗</a>'
                '<a href="https://broadbandmap.fcc.gov/location-summary/fixed?latlon=%.5f%%2C%.5f" target="_blank" rel="noopener noreferrer">FCC Broadband ↗</a>'
                '<a href="https://websoilsurvey.nrcs.usda.gov/app/" target="_blank" rel="noopener noreferrer">USDA Soils ↗</a>'
                '</div><p class="small" id="measure-out" aria-live="polite" style="margin-top:6px"></p>'
            ) % (la, lo, la, lo, la, lo)
            mapbox = (
                '<div id="parcel-map" class="map small"></div>'
                '<script type="application/json" id="parcel">%s</script>'
                '%s'
                '<p class="small">Switch layers (USGS Aerial, Topo, Streets, FEMA Flood Zones) top-right. Download KML/GPX for OnX Hunt, Gaia GPS, or Google Earth. Coordinates (%.5f, %.5f) are GIS reference only, not a boundary survey.</p>'
            ) % (json.dumps(parcel, separators=(",", ":")).replace("</", "<\\/"), diligence_links, la, lo)
            xray_section = (
                '<section class="xray-section" id="parcel-xray">'
                '<div class="xray-header"><div><div class="eyebrow">Live 9-Agency Federal Screening</div>'
                '<h2>Live Parcel X-Ray, Terrain Profile &amp; Land Potential</h2></div>'
                '<a class="button ghost sm no-print" href="%s#lat=%.5f&amp;lon=%.5f">Open full-screen X-Ray →</a></div>'
                '<div id="parcel-xray-body"><p class="small">Loading live USGS 9-point terrain cross-section, FEMA flood &amp; wildfire risk, USFWS wetlands, USDA soil/bedrock depth, Census road proximity, USGS public lands, and NASA solar/climate data…</p></div>'
                '</section>'
            ) % (self.u("/xray/"), la, lo)
        else:
            mapbox = '<p class="small">The source publishes no map coordinates for this listing. Use the official agency link for plat maps and sale documents.</p>'

        aq = urllib.parse.urlencode({k: v for k, v in (
            ("id", r["id"]), ("title", r["title"]),
            ("price", "" if r["price"] is None else r["price"]),
            ("acres", "" if not r["acres"] else r["acres"]),
        ) if v != ""})
        others = [x for x in county["listings"] if x["id"] != r["id"] and x["available"]][:6]

        has_price = r.get("price") is not None and r["price"] > 0
        concierge_fee = round(r["price"] * 0.10, 2) if has_price else None
        turnkey_total = round(r["price"] + concierge_fee, 2) if has_price else None

        kpi_price = esc(money(turnkey_total)) if has_price else "$20 to start"
        kpi_price_lbl = "Est. Turnkey Total (+10%)" if has_price else "Land Agent Acquisition"
        kpi_price_sub = (
            "%s official + %s (10%% Land Agent)" % (esc(money(r["price"])), esc(money(concierge_fee)))
            if has_price else "10% concierge transfer fee on close"
        )
        kpi_acres = esc(acres_text(r["acres"])) if r["acres"] else "Not stated"
        kpi_ppa = esc(money(r["price"])) if has_price else (
            esc(money(cv["value"]) + "/ac") if (cv and cv.get("value")) else "–"
        )
        kpi_ppa_lbl = ("Official Min Bid" if r["price_kind"] == "min_bid" else "Official Agency Price") if has_price else "County Benchmark"
        kpi_ppa_sub = (
            esc(money(r["price"] / r["acres"]) + "/ac official") if (has_price and r.get("acres"))
            else (esc(adapters.PRICE_KIND.get(r["price_kind"], "Agency figure")) if has_price
                  else (esc(cv["name"] + " avg") if (cv and cv.get("value")) else "See agency terms"))
        )
        kpi_right = esc(zoning_val) if zoning_val else (esc("Buildable: " + buildable_val) if buildable_val else esc(r["status_label"]))
        kpi_right_lbl = "Zoning" if zoning_val else ("Agency Flag" if buildable_val else "Offering Status")
        kpi_right_sub = esc(r["county_label"] + ", " + r["state"])

        summary_strip = (
            '<div class="dossier-metrics">'
            '<div class="kpi-card"><span>%s</span><strong>%s</strong><small>%s</small></div>'
            '<div class="kpi-card"><span>Lot / Tract Size</span><strong>%s</strong><small>Source figure (not a survey)</small></div>'
            '<div class="kpi-card"><span>%s</span><strong>%s</strong><small>%s</small></div>'
            '<div class="kpi-card"><span>%s</span><strong style="font-size:19px">%s</strong><small>%s</small></div>'
            '</div>'
        ) % (
            kpi_price_lbl, kpi_price, kpi_price_sub,
            kpi_acres, kpi_ppa_lbl, kpi_ppa, kpi_ppa_sub, kpi_right_lbl, kpi_right, kpi_right_sub,
        )

        print_checklist = (
            '<section class="print-checklist"><h2>On-Site Field Visit Checklist — %s</h2><ul>'
            '<li>&#9744; Recorded legal road access &amp; physical driveway grade verified</li>'
            '<li>&#9744; Corner pins / boundary markers located &amp; no encroachments</li>'
            '<li>&#9744; Distance to nearest power pole, transformer, or municipal tap</li>'
            '<li>&#9744; Drainage, flood line, low spots &amp; soil / perc feasibility checked</li>'
            '<li>&#9744; Zoning, setbacks &amp; agency eligibility rules confirmed directly</li>'
            '<li>&#9744; Back taxes, redemption rights, liens &amp; title path reviewed</li>'
            '</ul></section>'
        ) % esc(r["title"])

        if r["price_kind"] == "cash":
            agent_mode = "buy_now"
            agent_cta = "Buy &amp; Transfer with Land Agent — $20 →"
            agent_head = "Buy &amp; Transfer This Parcel Hands-Free"
            official_cta = "Prefer DIY? View official %s portal ↗" % esc(src.get("agency", "agency"))
        elif r["offering"] == "auction" or r["price_kind"] == "min_bid":
            agent_mode = "auction"
            agent_cta = "Bid &amp; Transfer with Land Agent — $20 →"
            agent_head = "Let Our Land Agent Vet, Bid &amp; Transfer"
            official_cta = "Prefer DIY? Bid directly on %s portal ↗" % esc(src.get("agency", "agency"))
        else:
            agent_mode = "landbank"
            agent_cta = "Acquire &amp; Transfer with Land Agent — $20 →"
            agent_head = "Let Our Land Agent Handle Application &amp; Deed Transfer"
            official_cta = "Prefer DIY? Apply directly on %s portal ↗" % esc(src.get("agency", "agency"))

        svc_q = urllib.parse.urlencode({k: v for k, v in (
            ("parcel", r["id"]), ("title", r["title"]),
            ("price", "" if not has_price else r["price"]),
            ("acres", "" if not r.get("acres") else r["acres"]),
            ("county", r["county_label"]), ("state", r["state"]),
            ("apn", r.get("apn") or ""), ("mode", agent_mode),
            ("lat", "" if r.get("lat") is None else r["lat"]),
            ("lon", "" if r.get("lon") is None else r["lon"]),
        ) if v != ""})

        if has_price:
            ledger_html = (
                '<div class="fee-ledger">'
                '<div class="fee-line"><span>Official agency %s</span><strong>%s</strong></div>'
                '<div class="fee-line"><span>Landosaur Land Agent fee (10%% on close)</span><strong>+%s</strong></div>'
                '<div class="fee-line total"><span>Estimated Turnkey Total</span><strong>%s</strong></div>'
                '<div class="fee-line due"><span>Due today to initiate full acquisition &amp; transfer</span><strong>$20.00</strong></div>'
                '</div>'
            ) % ("min bid" if r["price_kind"] == "min_bid" else "price", esc(money(r["price"])), esc(money(concierge_fee)), esc(money(turnkey_total)))
        else:
            ledger_html = (
                '<div class="fee-ledger">'
                '<div class="fee-line"><span>Official agency price</span><strong>Set via agency review / offer</strong></div>'
                '<div class="fee-line"><span>Landosaur Land Agent fee</span><strong>10%% only upon successful closing</strong></div>'
                '<div class="fee-line due"><span>Due today to initiate full acquisition &amp; transfer</span><strong>$20.00</strong></div>'
                '</div>'
            )

        agent_box = (
            '<div class="agent-checkout-card">'
            '<div class="eyebrow">Landosaur Land Agent · Full Acquisition &amp; Deed Transfer</div>'
            '<h3>%s</h3>%s'
            '<div class="btn-row" style="margin:12px 0 8px">'
            '<a class="button" href="%s?%s">%s</a>'
            '</div>'
            '<p class="small" style="margin:0">Includes county tax/lien &amp; redemption verification, agency paperwork or bid prep, and licensed title/deed closing coordination. '
            '<a data-official-source="1" href="%s" rel="noopener">%s</a></p>'
            '</div>'
        ) % (agent_head, ledger_html, self.u("/services/"), esc(svc_q), agent_cta, esc(r["url"]), official_cta)

        body = [
            crumbs,
            '<h1>%s</h1>' % esc(r["title"]),
            summary_strip,
            '<div class="dossier"><div class="dossier-card">%s<dl class="kv" style="margin-top:16px">%s</dl>'
            '<div class="btn-row">'
            '<a id="dossier-analyze-link" class="button ghost" href="%s?%s">Full Analyzer</a>'
            '<button type="button" id="print-dossier" class="button ghost sm">Print / Save Field PDF</button>'
            '<button type="button" id="save-parcel" class="button ghost sm" data-id="%s">Save ☆</button>'
            '<button type="button" id="compare-parcel" class="button ghost sm" data-id="%s">Compare</button>'
            '</div>'
            '<p class="callout"><strong>Not an offer to sell.</strong> Landosaur is an independent land database and acquisition concierge, not the government agency. %s\'s official rules, deadlines and '
            'eligibility terms apply; where state law requires a licensed broker or closing attorney, transfer is coordinated through a licensed local partner.</p></div><div>%s</div></div>' % (
                agent_box,
                "".join("<dt>%s</dt><dd>%s</dd>" % (k, v) for k, v in kv),
                self.u("/analyze/"), esc(aq), esc(r["id"]), esc(r["id"]),
                esc(src.get("agency", "The agency")), mapbox,
            ),
            xray_section,
            '<section><h2>What the official source says</h2><p>Read from the source on %s. Each fact links to where it was read.</p>'
            '<div class="scroll"><table class="data facts"><thead><tr><th scope="col">Fact</th><th scope="col">Value</th>'
            '<th scope="col">Source and notes</th></tr></thead><tbody>%s</tbody></table></div></section>' % (esc(r["checked"] or "an earlier date"), facts),
            context,
            self.worksheet(r),
            print_checklist,
            '<section class="callout no-print"><h2>Before you bid or apply</h2><p>Review our source-cited guides on '
            '<a href="%s">tax sales</a> · <a href="%s">legal road access</a> · <a href="%s">zoning &amp; buildability</a> · '
            '<a href="%s">flood risk</a> · <a href="%s">septic &amp; wells</a>.</p></section>' % (
                self.u("/research/tax-sales/"), self.u("/research/legal-road-access/"),
                self.u("/research/zoning-buildability/"), self.u("/research/flood-risk/"),
                self.u("/research/septic-feasibility/")),
        ]
        if others:
            body.append('<section class="no-print"><h2>More in %s</h2>%s<p><a href="%s">All listings in %s →</a></p></section>' % (
                esc(r["county_label"]), self.rows(others), self.u(cat.county_path(st, county)), esc(r["county_label"])))
        if config.REPORT_URL:
            body.append('<section class="callout no-print"><h2>Parcel report</h2><p>Want access, zoning, utility and cost unknowns checked for this parcel? '
                        '<a href="%s?listing=%s" rel="noopener">Order a parcel report</a> (separate paid service).</p></section>' % (
                            esc(config.REPORT_URL), esc(r["id"])))

        desc = "%s. %s; %s. Official listing from %s, read %s, with GIS map, live federal flood/soil/slope X-Ray, county benchmarks, and all-in cost worksheet." % (
            r["title"], price_line(r), acres_text(r["acres"]).lower(), src.get("agency", r["source"]), r["checked"] or "recently")
        idx = listing_is_indexable(r)
        return self.layout(
            "%s | Landosaur" % r["title"], desc, cat.listing_path(r), "".join(body),
            indexable=idx, jsonld=[crumb_ld], og="state-%s" % r["state"].lower(),
            scripts=["vendor/leaflet.js", "xray.js", "listing.js", "tables.js"], wide=True,
        )

    def worksheet(self, r):
        price = "" if r["price"] is None else ("%.2f" % r["price"]).rstrip("0").rstrip(".")
        fields = [
            ("price", "Price or winning bid", "$", price),
            ("fees", "Buyer's premium or auction fee", "%", ""),
            ("closing", "Deed, recording and closing costs", "$", ""),
            ("title", "Title search or title insurance", "$", ""),
            ("survey", "Survey", "$", ""),
            ("liens", "Back taxes, liens or quiet-title action", "$", ""),
            ("site", "Site work: clearing, driveway, grading", "$", ""),
            ("utilities", "Utilities: power, water or well, septic or sewer", "$", ""),
            ("tax", "Property tax per year", "$", ""),
            ("upkeep", "Insurance and upkeep per year", "$", ""),
            ("years", "Years you expect to hold it", "years", ""),
        ]
        inputs = "".join(
            '<label><span>%s</span><span class="in"><input name="%s" type="number" min="0" step="any" inputmode="decimal" value="%s">'
            '<i>%s</i></span></label>' % (esc(lbl), n, esc(v), esc(unit))
            for n, lbl, unit, v in fields
        )
        return (
            '<section><h2>Quick all-in cost worksheet</h2><p>Add your quotes and figures. Landosaur adds no estimates of its own; '
            'blank fields count as zero. Need land loans, balloons, or off-grid power math? Use the <a href="%s">Full Land Analyzer</a>.</p>'
            '<form class="worksheet" id="worksheet" data-acres="%s" onsubmit="return false">%s</form>'
            '<dl class="kv totals" id="totals" aria-live="polite"><dt>Buying it</dt><dd data-t="acq">–</dd><dt>Making it usable</dt>'
            '<dd data-t="site">–</dd><dt>Holding it</dt><dd data-t="hold">–</dd><dt>Total</dt><dd data-t="total">–</dd>'
            '<dt>Total per acre</dt><dd data-t="per">–</dd></dl><p><button type="button" id="copy-sheet" class="button ghost">Copy a link to these numbers</button></p>'
            '<noscript><p>The worksheet needs JavaScript.</p></noscript></section>'
        ) % (self.u("/analyze/"), r["acres"] or "", inputs)

    def _county_slug(self, r):
        from .model import slugify
        return slugify(r["county_label"])

    # ------------------------------------------------------------------ state and county
    def state(self, st):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("Land for Sale", "/land-for-sale/"), (st["name"], cat.state_path(st))])
        cur = [r for r in st["listings"] if r["available"]]
        by_src = {}
        for r in cur:
            by_src[r["source"]] = by_src.get(r["source"], 0) + 1
        src_text = "; ".join("%s from %s" % ("{:,}".format(n), esc(cat.sources[s]["agency"])) for s, n in sorted(by_src.items(), key=lambda x: -x[1]))
        counties = sorted(st["counties"].values(), key=lambda c: c["name"])
        rows = "".join(
            '<tr><th scope="row"><a href="%s">%s</a></th><td class="n" data-v="%d">%s</td><td class="n" data-v="%s">%s</td></tr>' % (
                self.u(cat.county_path(st, c)), esc(c["name"]),
                sum(1 for r in c["listings"] if r["available"]),
                "{:,}".format(sum(1 for r in c["listings"] if r["available"])),
                min([r["price"] for r in c["listings"] if r["available"] and r["price"]] or [""]),
                money(min([r["price"] for r in c["listings"] if r["available"] and r["price"]] or [None]), "–"),
            )
            for c in counties
        )
        body = [
            crumbs,
            "<h1>Government and auction land for sale in %s</h1>" % esc(st["name"]),
            '<p class="lede"><strong>%s</strong> current offerings: %s. Compare with <a href="%s">%s %d land prices per acre &amp; county values →</a></p>' % (
                "{:,}".format(len(cur)), src_text or "none right now",
                self.u("/land-prices/%s/" % st["slug"]), esc(st["name"]), self.market.latest_year),
            self.map_block(st["code"], "Map of %s listings" % st["name"]),
            '<section><h2>By county / jurisdiction</h2><div class="scroll"><table class="data sortable"><thead><tr><th scope="col">County</th>'
            '<th scope="col" class="n">Current listings</th><th scope="col" class="n">Lowest price or bid</th></tr></thead><tbody>%s</tbody></table></div></section>' % rows,
        ]
        closing = [r for r in cat.closing() if r["state"] == st["code"]][:20]
        if closing:
            body.append('<section><h2>Closing soon in %s</h2>%s</section>' % (esc(st["name"]), self.rows(closing, False, True)))
        body.append(
            '<section><h2>Use this data</h2><p><a href="%s">Atom feed of new %s listings</a> · '
            '<a href="%s">%s land price history</a> · <a href="%s">CSV of all listings</a></p></section>' % (
                self.u("/feeds/%s.xml" % st["code"].lower()), esc(st["name"]),
                self.u("/land-prices/%s/" % st["slug"]), esc(st["name"]), self.u("/data/listings.csv"))
        )
        desc = "%s government and auction land offerings in %s: %s. Interactive map, county lists, USDA land values, and official agency links." % (
            "{:,}".format(len(cur)), st["name"], src_text.replace("&amp;", "&") or "none right now")
        return self.layout(
            "Government and Auction Land for Sale in %s | Landosaur" % st["name"], desc, cat.state_path(st), "".join(body),
            indexable=True, jsonld=[crumb_ld], og="state-%s" % st["code"].lower(),
            scripts=["vendor/leaflet.js", "vendor/leaflet.markercluster.js", "map.js", "tables.js"], wide=True,
        )

    def county(self, st, c, group=None):
        cat = self.cat
        path = cat.county_path(st, c) + (group["slug"] + "/" if group else "")
        trail = [("Land for Sale", "/land-for-sale/"), (st["name"], cat.state_path(st)), (c["name"], cat.county_path(st, c))]
        if group:
            trail.append((group["name"], path))
        crumbs, crumb_ld = self.crumbs(trail)
        listings = group["listings"] if group else c["listings"]
        cur = [r for r in listings if r["available"]]
        name = c["name"] + (" (%s)" % group["name"] if group else "")
        body = [
            crumbs,
            "<h1>Land for sale in %s, %s</h1>" % (esc(name), esc(st["name"])),
            '<p class="lede"><strong>%s</strong> current government and auction offerings%s.</p>' % (
                "{:,}".format(len(cur)), "" if not group else " in this part of %s" % esc(c["name"])),
        ]
        if c["groups"] and not group:
            links = " · ".join(
                '<a href="%s%s/">%s</a> (%d)' % (
                    self.u(cat.county_path(st, c)), g["slug"], esc(g["name"]),
                    sum(1 for r in g["listings"] if r["available"]),
                )
                for g in c["groups"]
            )
            body.append('<section><h2>%s</h2><p>%s</p></section>' % (
                "By neighborhood" if not c["groups"][0]["slug"].startswith("page-") else "Pages", links))
        else:
            body.append('<section><h2>Listings</h2>%s</section>' % self.rows(listings, False, True))
        sample = next((r for r in listings), None)
        cv = cat.county_value(sample) if sample else None
        if cv and cv.get("value"):
            what = "land under single-family homes" if cv["kind"] == "r" else "farm real estate"
            body.append(
                '<section><h2>Land values in %s</h2><p>For context, %s in %s averaged <strong>%s per acre</strong> (%s) on the '
                '<a href="%s%s" rel="nofollow noopener noreferrer">US County Land Index</a>. '
                '<a href="%s">See all %s counties &amp; price history →</a></p></section>' % (
                    esc(c["name"]), what, esc(cv["name"]), money(cv["value"]), esc(str(cv["year"])),
                    esc(config.LAND_INDEX_URL), esc(cv["path"]),
                    self.u("/land-prices/%s/" % st["slug"]), esc(st["name"]),
                )
            )
        desc = "%s government and auction land offerings in %s, %s, each linked to its official agency listing with source-dated facts and GIS maps." % (
            "{:,}".format(len(cur)), name, st["name"])
        return self.layout(
            "Land for sale in %s, %s | Landosaur" % (name, st["name"]), desc, path, "".join(body),
            indexable=(group is None), jsonld=[crumb_ld], og="state-%s" % st["code"].lower(), scripts=["tables.js"], wide=True,
        )

    # ------------------------------------------------------------------ new, closing, sources, about, data
    def new(self):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("New listings", "/new/")])
        new = cat.new()
        body = [
            crumbs, "<h1>New government land listings</h1>",
            '<p class="lede">Land that official sources added in the last %d days: %s listings. Checked daily. '
            'Subscribe with the <a href="%s">Atom feed</a> or a state feed below.</p>' % (
                config.NEW_DAYS, "{:,}".format(len(new)), self.u("/feeds/new.xml")),
        ]
        if new:
            by_state = {}
            for r in new:
                by_state.setdefault(r["state"], []).append(r)
            for code in sorted(by_state, key=lambda c: STATE_NAMES.get(c, c)):
                body.append('<section><h2>%s</h2><p><a href="%s">Feed for %s</a></p>%s</section>' % (
                    esc(STATE_NAMES.get(code, code)), self.u("/feeds/%s.xml" % code.lower()),
                    esc(STATE_NAMES.get(code, code)), self.rows(by_state[code][:200], False, True)))
        else:
            body.append("<p>No new listings in the last %d days. The sources are read every day; this page and the feeds update when one adds land.</p>" % config.NEW_DAYS)
        body.append(self.how_block())
        desc = "New city, state and tax-sale land listings from official sources in the last %d days (%s), checked daily, with Atom feeds by state." % (
            config.NEW_DAYS, "{:,}".format(len(new)))
        ld = [crumb_ld, {
            "@context": "https://schema.org", "@type": "ItemList", "name": "New government land listings",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": self.absu(cat.listing_path(r)), "name": r["title"]}
                                for i, r in enumerate(new[:50])],
        }]
        return self.layout("New government and tax-sale land listings | Landosaur", desc, "/new/", "".join(body), indexable=True,
                           jsonld=ld, og="new", scripts=["tables.js"], wide=True)

    def closing(self):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("Closing soon", "/closing-soon/")])
        rows = cat.closing()
        body = [
            crumbs, "<h1>Land auctions and sales closing soon</h1>",
            '<p class="lede">Official land sales with a bid or application deadline in the next %d days: %s listings. '
            'Times are converted to UTC from the agency\'s stated local time; confirm the cutoff on the agency\'s page.</p>' % (
                config.CLOSING_DAYS, "{:,}".format(len(rows))),
        ]
        body.append(self.rows(rows[:500], True, True) if rows else "<p>No deadlines in the next %d days right now.</p>" % config.CLOSING_DAYS)
        body.append(self.how_block())
        desc = "Government land auctions and tax-sale parcels with deadlines in the next %d days (%s listings), from official sources, checked daily." % (
            config.CLOSING_DAYS, "{:,}".format(len(rows)))
        return self.layout("Government land auctions closing soon | Landosaur", desc, "/closing-soon/", "".join(body), indexable=True,
                           jsonld=[crumb_ld], og="closing", scripts=["tables.js"], wide=True)

    def sources_page(self):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("Sources", "/sources/")])
        rows = []
        for src in adapters.SOURCES:
            s = cat.status.get("sources", {}).get(src["id"], {})
            state = "read successfully" if s.get("ok") else ("failed: kept last good data" if s else "not read yet")
            rows.append(
                '<tr><th scope="row"><a href="%s" rel="noopener">%s</a><span class="sub">%s</span></th><td>%s</td><td class="n">%s</td>'
                '<td>%s</td><td>%s</td></tr>' % (
                    esc(src["url"]), esc(src["name"]), esc(src["about"]), esc(STATE_NAMES.get(src["state"])),
                    "{:,}".format(s.get("count") or 0), esc((s.get("last_success") or "")[:16].replace("T", " ")), esc(state))
            )
        missing = "".join('<li><a href="%s" rel="noopener">%s</a>: %s</li>' % (esc(u), esc(n), esc(why)) for n, u, why in adapters.NOT_CARRIED)
        body = [
            crumbs, "<h1>Official Government Land Data Sources</h1>",
            '<p class="lede">Every listing on Landosaur comes from a public agency\'s own inventory or open-data GIS feed. Each source is read daily with honest identification, robots.txt compliance, and polite pauses between requests.</p>',
            '<div class="scroll"><table class="data"><thead><tr><th scope="col">Source</th><th scope="col">State</th>'
            '<th scope="col" class="n">Current listings</th><th scope="col">Last read (UTC)</th><th scope="col">Status</th></tr></thead>'
            '<tbody>%s</tbody></table></div>' % "".join(rows),
            '<section><h2>Verification &amp; withdrawal rules</h2><ul class="notes">'
            '<li>A source that fails is retried, then kept on its last good snapshot; failures appear visibly above.</li>'
            '<li>A listing leaves the active catalog only after two consecutive complete reads omit it. Partial reads never wipe inventory.</li>'
            '<li>A source unchecked for %d days is marked stale and removed from active map defaults.</li>'
            '<li>Kept: parcel facts, zoning, GIS boundaries, deadlines, and agency links. Not kept: previous-owner personal names or scraped broker marketing copy.</li>'
            '</ul></section>' % config.CURRENT_DAYS,
            '<section><h2>Planned &amp; excluded sources</h2><ul class="notes">%s</ul></section>' % missing,
            '<section><h2>Machine-readable</h2><p><a href="%s">sources.json</a> · <a href="%s">listings.csv</a> · <a href="%s">Data downloads</a></p></section>' % (
                self.u("/data/sources.json"), self.u("/data/listings.csv"), self.u("/data/")),
        ]
        return self.layout(
            "Official Government Land Data Sources | Landosaur",
            "The %d official government land sources Landosaur tracks across %d states, last read timestamps, and verification rules." % (
                len(adapters.SOURCES), len(cat.states)),
            "/sources/", "".join(body), indexable=True, jsonld=[crumb_ld], wide=True,
        )

    def about(self):
        crumbs, crumb_ld = self.crumbs([("About", "/about/")])
        body = [
            crumbs, "<h1>About Landosaur</h1>",
            """
<p class="lede">Landosaur is building an open, evidence-first platform for finding, pricing, and vetting land: official city, county, state trust, and tax-sale parcels on one GIS map, paired with 50-state USDA/FHFA land price benchmarks, 29 due-diligence guides, and a deterministic valuation workbench.</p>
<section><h2>Who it is for</h2><p>Land buyers the residential portals underserve: neighbors who want the adjoining lot, homesteaders, small builders, farmers, community gardens, and land investors comparing rural acreage and government auctions.</p></section>
<section id="terms"><h2>What it is not (Terms &amp; Disclosures)</h2><p>Landosaur is not an offer to sell and does not sell, broker, or hold any land. It is not affiliated with the agencies it lists. It gives no legal, tax, title, or investment advice and does not appraise land. Minimum bids are not sale prices. Tax-sale land can carry redemption rights, title defects, liens, and unknown physical condition; confirm all terms directly with the agency and consult local title, survey, and legal professionals before bidding or buying.</p></section>
<section><h2>Ecosystem &amp; Open Data</h2><p>Landosaur reads official public land inventories daily and links every listing back to its authoritative government source. County-level land values per acre across 3,115 counties come from our sister reference, the <a href="%s/" rel="nofollow noopener noreferrer">US County Land Index</a>.</p></section>
<section><h2>Corrections</h2><p>If a listing is wrong or no longer available, the agency's page is authoritative. To report a site bug or suggest an official public land agency feed, <a href="%s" rel="noopener">open an issue on GitHub</a>.</p></section>
<section id="privacy"><h2>Privacy</h2><p>No accounts, no advertising cookies, and the cost worksheet, Analyzer workbench, shortlist, and parcel comparison run entirely in your browser (localStorage / URL hash) without submitting your numbers to a server (with cookieless aggregate page telemetry).</p></section>
""" % (esc(config.LAND_INDEX_URL), esc(config.REPO_URL + "/issues")),
        ]
        return self.layout(
            "About Landosaur — Government & Auction Land Map",
            "Landosaur maps official government and auction land offerings with 50-state USDA land prices and valuation tools. Not an offer to sell; no advice.",
            "/about/", "".join(body), indexable=True, jsonld=[crumb_ld],
        )

    def data_page(self, files):
        crumbs, crumb_ld = self.crumbs([("Data", "/data/")])
        rows = "".join('<tr><th scope="row"><a href="%s">%s</a></th><td>%s</td></tr>' % (self.u(p), esc(p.rsplit("/", 1)[-1]), esc(d)) for p, d in files)
        body = [
            crumbs, "<h1>Open Data Downloads</h1>",
            '<p class="lede">Download Landosaur\'s complete verified official land catalog as CSV or JSON. Facts belong to the public agencies that publish them; confirm terms before reusing agency data.</p>',
            '<div class="scroll"><table class="data"><thead><tr><th scope="col">File</th><th scope="col">Contents</th></tr></thead><tbody>%s</tbody></table></div>' % rows,
            '<p>Atom feeds: <a href="%s">all new listings</a>, plus one feed per tracked state under <code>/feeds/</code>.</p>' % self.u("/feeds/new.xml"),
        ]
        return self.layout(
            "Government Land Data Downloads (CSV & JSON) | Landosaur",
            "Download Landosaur's verified official government land listings as CSV and JSON, plus source health status and Atom XML feeds.",
            "/data/", "".join(body), indexable=True, jsonld=[crumb_ld],
        )

    def not_found(self):
        body = (
            '<h1>Page not found</h1><p class="lede">That page is not here. Listings that leave an agency\'s inventory are removed after two daily checks.</p>'
            '<p><a href="%s">Open the land map</a> · <a href="%s">Browse 50-state land prices</a> · <a href="%s">Land Analyzer</a> · <a href="%s">Research guides</a></p>' % (
                self.u("/"), self.u("/land-prices/"), self.u("/analyze/"), self.u("/research/"))
        )
        return self.layout("Page not found | Landosaur", "Page not found on Landosaur.", "/404.html", body, indexable=False)
