"""Page templates. Every number on a page comes from the stored listings or the source status."""
import html
import json

from . import adapters, config
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
    "neighborhood": "Neighbourhood", "ward": "Ward", "side_lot_eligible": "Side-lot program", "irregular_lot": "Irregular lot",
    "how_the_city_acquired_it": "How the city acquired it", "parcel_outline": "Parcel outline", "file_number": "Agency file number",
    "tax_parcel_id": "Tax parcel ID", "sale_program": "Sale program", "access": "Access", "agency_description_excerpt": "Agency description",
    "agency_map": "Agency map", "bid_deadline": "Bid deadline", "trust_parcel_number": "Trust parcel number", "road_access": "Road access",
    "dnr_parcel": "DNR parcel", "program": "Program", "water_access": "Water access", "remote_access": "Remote access",
    "alaska_residents_only": "Alaska residents only", "region": "Region", "case_file": "Case file",
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


class Site(object):
    def __init__(self, catalog):
        self.cat = catalog
        self.base = config.base_path()

    def u(self, path):
        return self.base + path

    def absu(self, path):
        return config.BASE_URL + path

    def layout(self, title, description, path, body, indexable=False, jsonld=None, og="default", scripts=(), wide=False):
        """indexable: True only for pages the original application does not serve, and only when SITE_INDEXABLE."""
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
            '<link rel="stylesheet" href="%s">' % self.u("/assets/style.css"),
            '<link rel="alternate" type="application/atom+xml" title="New government land listings" href="%s">' % self.u("/feeds/new.xml"),
            '<script src="https://rsio.org/vital.js" defer></script>',
        ]
        if any("map" in s or "listing" in s for s in scripts):
            head.append('<link rel="stylesheet" href="%s">' % self.u("/assets/vendor/leaflet.css"))
            head.append('<link rel="stylesheet" href="%s">' % self.u("/assets/vendor/MarkerCluster.css"))
            head.append('<link rel="stylesheet" href="%s">' % self.u("/assets/vendor/MarkerCluster.Default.css"))
        for block in jsonld or []:
            head.append('<script type="application/ld+json">%s</script>' % json.dumps(block, separators=(",", ":")).replace("</", "<\\/"))
        nav = "".join('<a href="%s">%s</a>' % (self.u(p), t) for p, t in (
            ("/", "Map"), ("/new/", "New"), ("/closing-soon/", "Closing soon"), ("/sources/", "Sources"), ("/about/", "About")))
        extra = ""
        if config.SUPPORT_URL:
            extra += ' · <a href="%s" rel="noopener sponsored">Support Landosaur</a>' % esc(config.SUPPORT_URL)
        foot = ('<footer><div class="wrap"><p class="notice">%s</p><p>Sources: %s. <a href="%s">How sources are read</a>.</p>'
                '<p>Land values per acre by county: <a href="%s/">US County Land Index</a>. The full Landosaur application '
                '(accounts, worksheets, buying help) runs at <a href="%s/" rel="noopener">%s</a>.</p>'
                '<p><a href="%s">About</a> · <a href="%s">Data downloads</a> · <a href="%s" rel="noopener">Source code</a> · '
                '<a href="%s" rel="noopener">Report a problem</a>%s</p></div></footer>') % (
            esc(NOTICE), ", ".join(esc(s["agency"]) for s in adapters.SOURCES), self.u("/sources/"), esc(config.LAND_INDEX_URL),
            esc(config.ORIGINAL_URL), esc(config.ORIGINAL_URL.split("://")[-1]), self.u("/about/"), self.u("/data/"),
            esc(config.REPO_URL), esc(config.REPO_URL + "/issues"), extra)
        tail = "".join('<script src="%s" defer></script>' % self.u("/assets/" + s) for s in scripts)
        if config.GOATCOUNTER:
            tail += '<script data-goatcounter="%s" async src="https://gc.zgo.at/count.js"></script>' % esc(config.GOATCOUNTER)
        return ('<!doctype html><html lang="en"><head>%s</head><body data-base="%s"><a class="skip" href="#main">Skip to content</a>'
                '<header><div class="wrap"><a class="brand" href="%s">%s<span>Landosaur</span></a><nav aria-label="Main">%s</nav></div></header>'
                '<main id="main" class="wrap%s">%s</main>%s%s</body></html>') % (
            "".join(head), esc(self.base), self.u("/"), DINO, nav, " wide" if wide else "", body, foot, tail)

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
        if r["status"] in ("auction_open", "auction_terms") and r["available"]:
            cls = "auction"
        label = r["status_label"] if r["fresh"] else "Not re-checked recently"
        return '<span class="badge %s">%s</span>' % (cls if r["fresh"] else "off", esc(label))

    def rows(self, listings, show_state=False):
        out = []
        for r in listings:
            where = r["county_label"] + (", " + r["state"] if show_state else "")
            out.append('<tr><th scope="row"><a href="%s">%s</a><span class="sub">%s</span></th><td data-label="Status">%s</td>'
                       '<td class="n" data-label="Price" data-v="%s">%s</td><td class="n" data-label="Acres" data-v="%s">%s</td>'
                       '<td data-label="Deadline">%s</td></tr>' % (
                           self.u(self.cat.listing_path(r)), esc(r["title"]), esc(where), self.badge(r),
                           r["price"] if r["price"] is not None else "", esc(price_line(r)) if r["price"] is not None else "–",
                           r["acres"] or "", esc(acres_text(r["acres"])) if r["acres"] else "–",
                           esc(date_text(r.get("deadline"))) or "–"))
        return ('<div class="scroll"><table class="data sortable listings"><thead><tr><th scope="col">Listing</th><th scope="col">Status</th>'
                '<th scope="col" class="n">Price or minimum bid</th><th scope="col" class="n">Acres</th><th scope="col">Deadline</th>'
                '</tr></thead><tbody>%s</tbody></table></div>' % "".join(out))

    def updated(self):
        return (self.cat.status.get("checked") or "")[:10]

    # ------------------------------------------------------------------ home (map)
    def home(self):
        cat = self.cat
        cur = cat.current()
        n_src = sum(1 for s in cat.status.get("sources", {}).values() if s.get("count"))
        states = sorted({r["state"] for r in cur})
        state_list = ", ".join(STATE_NAMES[s] for s in states) or "participating states"
        lede = ("<strong>%s</strong> rural, municipal, and government auction land offerings from %d official agencies in %s, "
                "read daily from public inventories—covering raw acreage, tax-forfeited parcels, surplus state trust land, and city lots, "
                "with GIS parcel outlines, county land value context, and direct official agency links." % ("{:,}".format(len(cur)), n_src, state_list))
        state_links = " · ".join('<a href="%s">%s</a> (%s)' % (self.u(cat.state_path(st)), esc(st["name"]), "{:,}".format(
            sum(1 for r in st["listings"] if r["available"]))) for st in sorted(cat.states.values(), key=lambda s: s["name"]))
        new = cat.new()[:8]
        closing = cat.closing()[:8]
        faqs = [
            (
                "How can I research rural land, raw acreage, and county tax-sale parcels directly from government agencies?",
                "Landosaur maps %s active public-agency land offerings across %s from %d official government agencies—covering rural state trust acreage, tax-forfeited county auction parcels, and municipal land-bank lots—with state/price/acreage filters, agency GIS parcel outlines, county USDA/FHFA land value context, and direct official agency links." % ("{:,}".format(len(cur)), state_list, n_src),
            ),
            (
                "Does Landosaur sell, broker, or take commissions on government land?",
                "No. Landosaur is an independent public reference map, not an offer to sell and not a broker. Every listing links directly to the source government agency's official page so buyers verify terms, liens, and deadlines directly.",
            ),
            (
                "How does Landosaur differ from commercial land marketplaces?",
                "Landosaur reads only official public-agency inventories (never commercial brokerage scrapes), never invents asking prices where an agency publishes none, labels minimum bids separately from fixed prices, and provides free bulk CSV/JSON downloads and Atom feeds.",
            ),
            (
                "How often are official agency land inventories updated?",
                "Each official agency inventory is checked daily. Failed or partial reads preserve the last verified snapshot, and a parcel leaves the active map only after two consecutive complete agency reads omit it.",
            ),
        ]
        faq_html = "".join("<details><summary>%s</summary><p>%s</p></details>" % (esc(q), esc(a)) for q, a in faqs)
        body = [
            '<section class="hero"><img src="%s" alt="" width="96" height="96" class="mascot"><div><h1>Government and auction land for sale, on one map</h1>'
            '<p class="lede">%s</p></div></section>' % (self.u("/assets/mascot.png"), lede),
            self.map_block("all"),
            '<section><h2>Browse by state</h2><p>%s</p></section>' % state_links,
        ]
        if new:
            body.append('<section><h2>New this fortnight</h2>%s<p><a href="%s">All new listings</a> · <a href="%s">Atom feed</a></p></section>' % (
                self.rows(new, True), self.u("/new/"), self.u("/feeds/new.xml")))
        if closing:
            body.append('<section><h2>Deadlines in the next %d days</h2>%s<p><a href="%s">Everything closing soon</a></p></section>' % (
                config.CLOSING_DAYS, self.rows(closing, True), self.u("/closing-soon/")))
        body.append(self.how_block())
        body.append('<section id="faq"><h2>Frequently asked questions</h2>%s</section>' % faq_html)
        desc = ("Explore %s official rural, tax-sale, and government auction land offerings across %s: raw acreage, county parcels, "
                "GIS outlines, USDA/FHFA land value benchmarks, and direct agency links.") % ("{:,}".format(len(cur)), state_list)
        ld = [{
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebSite", "@id": self.absu("/#website"), "name": "Landosaur", "url": self.absu("/"), "description": desc},
                {
                    "@type": "SoftwareApplication",
                    "@id": self.absu("/#webapp"),
                    "name": "Landosaur Public-Agency Land & County Parcel Map",
                    "applicationCategory": "ReferenceApplication",
                    "operatingSystem": "Web",
                    "url": self.absu("/"),
                    "description": desc,
                    "isAccessibleForFree": True,
                    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                },
                {
                    "@type": "Dataset",
                    "@id": self.absu("/#dataset"),
                    "name": "Landosaur Official Government & Auction Land Catalog",
                    "description": desc,
                    "url": self.absu("/data/"),
                    "isAccessibleForFree": True,
                    "distribution": [
                        {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": self.absu("/data/listings.csv")},
                        {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": self.absu("/data/map.json")},
                    ],
                },
                {
                    "@type": "FAQPage",
                    "@id": self.absu("/#faq"),
                    "mainEntity": [
                        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                        for q, a in faqs
                    ],
                },
            ],
        }]
        return self.layout("Rural, Government & Auction Land for Sale on One Map | Landosaur", desc, "/", "".join(body), jsonld=ld,
                           scripts=["vendor/leaflet.js", "vendor/leaflet.markercluster.js", "map.js", "tables.js"], wide=True)

    def map_block(self, scope, title="Map"):
        states = sorted(self.cat.states.values(), key=lambda s: s["name"])
        opts = "".join('<option value="%s"%s>%s</option>' % (s["code"], " selected" if scope == s["code"] else "", esc(s["name"])) for s in states)
        return (
            '<section class="mapzone" aria-label="%s"><form class="filters" id="filters" onsubmit="return false">'
            '<label>State<select name="state"><option value="">All states</option>%s</select></label>'
            '<label>Type<select name="kind"><option value="">Any</option><option value="cash">Fixed price</option>'
            '<option value="min_bid">Auction or minimum bid</option><option value="none">No price published</option></select></label>'
            '<label>Max price<input name="max" type="number" min="0" step="100" inputmode="numeric" placeholder="Any"></label>'
            '<label>Min acres<input name="acres" type="number" min="0" step="0.1" inputmode="decimal" placeholder="Any"></label>'
            '<label class="grow">Search<input name="q" type="search" placeholder="Address, parcel, county"></label>'
            '<label class="check"><input name="closed" type="checkbox"> Include closed and pending</label></form>'
            '<div id="map" class="map" data-scope="%s"><noscript><p>The map needs JavaScript. Use the state pages below.</p></noscript></div>'
            '<p class="small" id="map-count" aria-live="polite"></p><div id="results" class="results"></div></section>'
        ) % (esc(title), opts, esc(scope))

    def how_block(self):
        return ('<section><h2>How Landosaur works</h2><ul class="notes">'
                '<li><strong>Official sources only.</strong> City, state and auction agencies\' own inventories, read once a day. '
                'Nothing is copied from commercial listing portals.</li>'
                '<li><strong>Facts with dates.</strong> Each listing shows what the agency published, when it was read, and a link back.</li>'
                '<li><strong>No invented prices.</strong> Where an agency publishes no price, none is shown. A minimum bid is not a sale price.</li>'
                '<li><strong>Your costs, your numbers.</strong> Each listing has an all-in cost worksheet for the quotes you collect.</li>'
                '</ul><p><a href="%s">More about the sources and the rules</a></p></section>' % self.u("/about/"))

    # ------------------------------------------------------------------ listing
    def listing(self, r):
        cat = self.cat
        st = cat.states[r["state"]]
        county = st["counties"][self._county_slug(r)]
        trail = [(st["name"], cat.state_path(st)), (county["name"], cat.county_path(st, county)), (r["title"], cat.listing_path(r))]
        crumbs, crumb_ld = self.crumbs(trail)
        src = cat.sources.get(r["source"], {})
        kv = [("Status", self.badge(r)), ("Price", esc(price_line(r))), ("Acres", esc(acres_text(r["acres"]))),
              ("Location", esc(", ".join(x for x in (r.get("address"), r.get("locality"), r["county_label"], r["state_name"]) if x)))]
        if r.get("apn"):
            kv.append(("Parcel", esc(r["apn"])))
        if r.get("deadline"):
            kv.append(("Deadline", esc(r["deadline"][:16].replace("T", " ") + " UTC")))
        kv.append(("Source", '<a href="%s" rel="noopener">%s</a>' % (esc(src.get("url", r["url"])), esc(src.get("agency", r["source"])))))
        kv.append(("Last read", esc(r["checked"] or "unknown")))
        if r.get("first_seen"):
            kv.append(("First seen", esc(r["first_seen"])))
        facts = "".join('<tr><th scope="row">%s</th><td>%s</td><td>%s%s</td></tr>' % (
            esc(NICE_TOPIC.get(f["topic"], f["topic"].replace("_", " ").capitalize())), esc(f["value"]),
            ('<a href="%s" rel="noopener">%s</a>' % (esc(adapters.expand_url(r, f["url"])), "source")) if f.get("url") else "",
            (' <span class="note">%s</span>' % esc(adapters.note_text(f["note"]))) if f.get("note") else "") for f in r["facts"])
        context = ""
        cv = cat.county_value(r)
        if cv and cv.get("value"):
            kind = {"c": "%d census" % cv["year"], "e": "%d estimate" % cv["year"], "i": "%d estimate" % cv["year"],
                    "r": "%d residential land, FHFA" % cv["year"]}.get(cv["kind"], str(cv["year"]))
            per = ""
            if r["price"] and r["acres"]:
                per = " This listing's %s works out to %s per acre." % (
                    "minimum bid" if r["price_kind"] == "min_bid" else "price", money(r["price"] / r["acres"]))
            what = "Land under single-family homes" if cv["kind"] == "r" else "Farm real estate"
            context = ('<section><h2>Land values in %s</h2><p>%s in %s averaged <strong>%s per acre</strong> (%s) on the '
                       '<a href="%s%s">US County Land Index</a>.%s County averages mix very different land; they are context, '
                       'not an appraisal of this parcel.</p></section>') % (
                esc(r["county_label"]), what, esc(cv["name"] + ", " + r["state_name"]), money(cv["value"]), esc(kind),
                esc(config.LAND_INDEX_URL), esc(cv["path"]), per)
        parcel = {"lat": r.get("lat"), "lon": r.get("lon"), "geometry": r.get("geometry"), "title": r["title"]}
        mapbox = ('<div id="parcel-map" class="map small"></div><script type="application/json" id="parcel">%s</script>'
                  '<p class="small">Outline and pin from the agency\'s GIS; not a survey.</p>' % json.dumps(parcel, separators=(",", ":")).replace("</", "<\\/")
                  ) if r.get("lat") is not None else '<p class="small">The source publishes no map location for this listing. Use the agency link for maps and documents.</p>'
        others = [x for x in county["listings"] if x["id"] != r["id"] and x["available"]][:6]
        body = [
            crumbs, '<h1>%s</h1>' % esc(r["title"]),
            '<div class="dossier"><div><dl class="kv">%s</dl><p><a class="button" href="%s" rel="noopener">View this listing on the agency\'s site</a></p>'
            '<p class="callout"><strong>Not an offer to sell.</strong> Landosaur does not sell or broker this land. %s\'s terms, deadlines and '
            'eligibility rules apply; buy only through the agency.</p></div><div>%s</div></div>' % (
                "".join("<dt>%s</dt><dd>%s</dd>" % (k, v) for k, v in kv), esc(r["url"]), esc(src.get("agency", "The agency")), mapbox),
            '<section><h2>What the source says</h2><p>Read from the source on %s. Each fact links to where it was read.</p>'
            '<div class="scroll"><table class="data facts"><thead><tr><th scope="col">Fact</th><th scope="col">Value</th>'
            '<th scope="col">Source and notes</th></tr></thead><tbody>%s</tbody></table></div></section>' % (esc(r["checked"] or "an earlier date"), facts),
            context, self.worksheet(r),
        ]
        if others:
            body.append('<section><h2>More in %s</h2>%s<p><a href="%s">All listings in %s</a></p></section>' % (
                esc(r["county_label"]), self.rows(others), self.u(cat.county_path(st, county)), esc(r["county_label"])))
        if config.REPORT_URL:
            body.append('<section class="callout"><h2>Parcel report</h2><p>Want access, zoning, utility and cost unknowns checked for this parcel? '
                        '<a href="%s?listing=%s" rel="noopener">Order a parcel report</a> (separate paid service).</p></section>' % (
                            esc(config.REPORT_URL), esc(r["id"])))
        desc = "%s. %s; %s. Official listing from %s, read %s, with source-dated facts, map and an all-in cost worksheet." % (
            r["title"], price_line(r), acres_text(r["acres"]).lower(), src.get("agency", r["source"]), r["checked"] or "recently")
        return self.layout("%s | Landosaur" % r["title"], desc, cat.listing_path(r), "".join(body), jsonld=[crumb_ld],
                           og="state-%s" % r["state"].lower(), scripts=["vendor/leaflet.js", "listing.js", "tables.js"])

    def worksheet(self, r):
        price = "" if r["price"] is None else ("%.2f" % r["price"]).rstrip("0").rstrip(".")
        fields = [("price", "Price or winning bid", "$", price), ("fees", "Buyer's premium or auction fee", "%", ""),
                  ("closing", "Deed, recording and closing costs", "$", ""), ("title", "Title search or title insurance", "$", ""),
                  ("survey", "Survey", "$", ""), ("liens", "Back taxes, liens or quiet-title action", "$", ""),
                  ("site", "Site work: clearing, driveway, grading", "$", ""), ("utilities", "Utilities: power, water or well, septic or sewer", "$", ""),
                  ("tax", "Property tax per year", "$", ""), ("upkeep", "Insurance and upkeep per year", "$", ""),
                  ("years", "Years you expect to hold it", "years", "")]
        inputs = "".join('<label><span>%s</span><span class="in"><input name="%s" type="number" min="0" step="any" inputmode="decimal" value="%s">'
                         '<i>%s</i></span></label>' % (esc(lbl), n, esc(v), esc(unit)) for n, lbl, unit, v in fields)
        return ('<section><h2>All-in cost worksheet</h2><p>Add the quotes and figures you collect. Landosaur adds no estimates of its own; '
                'blank fields count as zero.</p><form class="worksheet" id="worksheet" data-acres="%s" onsubmit="return false">%s</form>'
                '<dl class="kv totals" id="totals" aria-live="polite"><dt>Buying it</dt><dd data-t="acq">–</dd><dt>Making it usable</dt>'
                '<dd data-t="site">–</dd><dt>Holding it</dt><dd data-t="hold">–</dd><dt>Total</dt><dd data-t="total">–</dd>'
                '<dt>Total per acre</dt><dd data-t="per">–</dd></dl><p><button type="button" id="copy-sheet" class="button ghost">Copy a link to these numbers</button></p>'
                '<noscript><p>The worksheet needs JavaScript.</p></noscript></section>') % (r["acres"] or "", inputs)

    def _county_slug(self, r):
        from .model import slugify
        return slugify(r["county_label"])

    # ------------------------------------------------------------------ state and county
    def state(self, st):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([(st["name"], cat.state_path(st))])
        cur = [r for r in st["listings"] if r["available"]]
        by_src = {}
        for r in cur:
            by_src[r["source"]] = by_src.get(r["source"], 0) + 1
        src_text = "; ".join("%s from %s" % ("{:,}".format(n), esc(cat.sources[s]["agency"])) for s, n in sorted(by_src.items(), key=lambda x: -x[1]))
        counties = sorted(st["counties"].values(), key=lambda c: c["name"])
        rows = "".join('<tr><th scope="row"><a href="%s">%s</a></th><td class="n" data-v="%d">%s</td><td class="n" data-v="%s">%s</td></tr>' % (
            self.u(cat.county_path(st, c)), esc(c["name"]), sum(1 for r in c["listings"] if r["available"]),
            "{:,}".format(sum(1 for r in c["listings"] if r["available"])),
            min([r["price"] for r in c["listings"] if r["available"] and r["price"]] or [""]),
            money(min([r["price"] for r in c["listings"] if r["available"] and r["price"]] or [None]), "–")) for c in counties)
        body = [crumbs, "<h1>Government and auction land for sale in %s</h1>" % esc(st["name"]),
                '<p class="lede"><strong>%s</strong> current offerings: %s.</p>' % ("{:,}".format(len(cur)), src_text or "none right now"),
                self.map_block(st["code"], "Map of %s listings" % st["name"]),
                '<section><h2>By county</h2><div class="scroll"><table class="data sortable"><thead><tr><th scope="col">County</th>'
                '<th scope="col" class="n">Current listings</th><th scope="col" class="n">Lowest price or bid</th></tr></thead><tbody>%s</tbody></table></div></section>' % rows]
        closing = [r for r in cat.closing() if r["state"] == st["code"]][:20]
        if closing:
            body.append('<section><h2>Closing soon</h2>%s</section>' % self.rows(closing))
        body.append('<section><h2>Use this data</h2><p><a href="%s">Atom feed of new %s listings</a> · <a href="%s">CSV of all listings</a></p></section>' % (
            self.u("/feeds/%s.xml" % st["code"].lower()), esc(st["name"]), self.u("/data/listings.csv")))
        desc = "%s government and auction land offerings in %s: %s. Map, county lists and official source links." % (
            "{:,}".format(len(cur)), st["name"], src_text.replace("&amp;", "&") or "none right now")
        return self.layout("Government and auction land for sale in %s | Landosaur" % st["name"], desc, cat.state_path(st), "".join(body),
                           jsonld=[crumb_ld], og="state-%s" % st["code"].lower(),
                           scripts=["vendor/leaflet.js", "vendor/leaflet.markercluster.js", "map.js", "tables.js"], wide=True)

    def county(self, st, c, group=None):
        cat = self.cat
        path = cat.county_path(st, c) + (group["slug"] + "/" if group else "")
        trail = [(st["name"], cat.state_path(st)), (c["name"], cat.county_path(st, c))]
        if group:
            trail.append((group["name"], path))
        crumbs, crumb_ld = self.crumbs(trail)
        listings = group["listings"] if group else c["listings"]
        cur = [r for r in listings if r["available"]]
        name = c["name"] + (" (%s)" % group["name"] if group else "")
        body = [crumbs, "<h1>Land for sale in %s, %s</h1>" % (esc(name), esc(st["name"])),
                '<p class="lede"><strong>%s</strong> current government and auction offerings%s.</p>' % (
                    "{:,}".format(cur and len(cur) or 0), "" if not group else " in this part of %s" % esc(c["name"]))]
        if c["groups"] and not group:
            links = " · ".join('<a href="%s%s/">%s</a> (%d)' % (self.u(cat.county_path(st, c)), g["slug"], esc(g["name"]),
                                                                  sum(1 for r in g["listings"] if r["available"])) for g in c["groups"])
            body.append('<section><h2>%s</h2><p>%s</p></section>' % (
                "By neighbourhood" if not c["groups"][0]["slug"].startswith("page-") else "Pages", links))
        else:
            body.append('<section><h2>Listings</h2>%s</section>' % self.rows(listings))
        sample = next((r for r in listings), None)
        cv = cat.county_value(sample) if sample else None
        if cv and cv.get("value"):
            what = "land under single-family homes" if cv["kind"] == "r" else "farm real estate"
            body.append('<section><h2>Land values</h2><p>For context, %s in %s averaged %s per acre (%s) on the '
                        '<a href="%s%s">US County Land Index</a>.</p></section>' % (
                            what, esc(cv["name"]), money(cv["value"]), esc(str(cv["year"])), esc(config.LAND_INDEX_URL), esc(cv["path"])))
        desc = "%s government and auction land offerings in %s, %s, each linked to the agency's listing with source-dated facts." % (
            "{:,}".format(len(cur)), name, st["name"])
        return self.layout("Land for sale in %s, %s | Landosaur" % (name, st["name"]), desc, path, "".join(body), jsonld=[crumb_ld],
                           og="state-%s" % st["code"].lower(), scripts=["tables.js"])

    # ------------------------------------------------------------------ new, closing, sources, about, data
    def new(self):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("New listings", "/new/")])
        new = cat.new()
        body = [crumbs, "<h1>New government land listings</h1>",
                '<p class="lede">Land that official sources added in the last %d days: %s listings. Checked daily. '
                'Subscribe with the <a href="%s">Atom feed</a> or a state feed below.</p>' % (config.NEW_DAYS, "{:,}".format(len(new)), self.u("/feeds/new.xml"))]
        if new:
            by_state = {}
            for r in new:
                by_state.setdefault(r["state"], []).append(r)
            for code in sorted(by_state, key=lambda c: STATE_NAMES.get(c, c)):
                body.append('<section><h2>%s</h2><p><a href="%s">Feed for %s</a></p>%s</section>' % (
                    esc(STATE_NAMES.get(code, code)), self.u("/feeds/%s.xml" % code.lower()), esc(STATE_NAMES.get(code, code)),
                    self.rows(by_state[code][:200])))
        else:
            body.append("<p>No new listings in the last %d days. The sources are read every day; this page and the feeds update when one adds land.</p>" % config.NEW_DAYS)
        body.append(self.how_block())
        desc = "New city, state and tax-sale land listings from official sources in the last %d days (%s), checked daily, with Atom feeds by state." % (
            config.NEW_DAYS, "{:,}".format(len(new)))
        ld = [crumb_ld, {"@context": "https://schema.org", "@type": "ItemList", "name": "New government land listings",
                         "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": self.absu(cat.listing_path(r)), "name": r["title"]}
                                             for i, r in enumerate(new[:50])]}]
        return self.layout("New government and tax-sale land listings | Landosaur", desc, "/new/", "".join(body), indexable=True,
                           jsonld=ld, og="new", scripts=["tables.js"])

    def closing(self):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("Closing soon", "/closing-soon/")])
        rows = cat.closing()
        body = [crumbs, "<h1>Land auctions and sales closing soon</h1>",
                '<p class="lede">Official land sales with a bid or application deadline in the next %d days: %s listings. '
                'Times are converted to UTC from the agency\'s stated local time; confirm the cutoff on the agency\'s page.</p>' % (
                    config.CLOSING_DAYS, "{:,}".format(len(rows)))]
        body.append(self.rows(rows[:500], True) if rows else "<p>No deadlines in the next %d days right now.</p>" % config.CLOSING_DAYS)
        body.append(self.how_block())
        desc = "Government land auctions and tax-sale parcels with deadlines in the next %d days (%s listings), from official sources, checked daily." % (
            config.CLOSING_DAYS, "{:,}".format(len(rows)))
        return self.layout("Government land auctions closing soon | Landosaur", desc, "/closing-soon/", "".join(body), indexable=True,
                           jsonld=[crumb_ld], og="closing", scripts=["tables.js"])

    def sources_page(self):
        cat = self.cat
        crumbs, crumb_ld = self.crumbs([("Sources", "/sources/")])
        rows = []
        for src in adapters.SOURCES:
            s = cat.status.get("sources", {}).get(src["id"], {})
            state = "read successfully" if s.get("ok") else ("failed: kept last good data" if s else "not read yet")
            rows.append('<tr><th scope="row"><a href="%s" rel="noopener">%s</a><span class="sub">%s</span></th><td>%s</td><td class="n">%s</td>'
                        '<td>%s</td><td>%s</td></tr>' % (esc(src["url"]), esc(src["name"]), esc(src["about"]), esc(STATE_NAMES.get(src["state"])),
                                                        "{:,}".format(s.get("count") or 0), esc((s.get("last_success") or "")[:16].replace("T", " ")),
                                                        esc(state)))
        missing = "".join('<li><a href="%s" rel="noopener">%s</a>: %s</li>' % (esc(u), esc(n), esc(why)) for n, u, why in adapters.NOT_CARRIED)
        body = [crumbs, "<h1>Sources</h1>",
                '<p class="lede">Every listing comes from an agency\'s own public inventory. Each source is read once a day by a '
                'scheduled job that identifies itself, respects robots.txt and pauses between requests.</p>',
                '<div class="scroll"><table class="data"><thead><tr><th scope="col">Source</th><th scope="col">State</th>'
                '<th scope="col" class="n">Current listings</th><th scope="col">Last read (UTC)</th><th scope="col">Status</th></tr></thead>'
                '<tbody>%s</tbody></table></div>' % "".join(rows),
                '<section><h2>Rules</h2><ul class="notes"><li>A source that fails is retried, then kept on its last good data; the failure shows here.</li>'
                '<li>A listing leaves the map only after two complete reads of its source in a row no longer include it. A failed or partial read never removes anything, and disappearance is never treated as a sale.</li>'
                '<li>A listing whose source has not been read successfully for %d days is shown as not re-checked and is left off the map.</li>'
                '<li>Kept: facts about the land and the offering. Not kept: names of previous owners, photographs, marketing text.</li></ul></section>' % config.CURRENT_DAYS,
                '<section><h2>Not carried yet</h2><ul class="notes">%s</ul></section>' % missing,
                '<section><h2>Machine-readable</h2><p><a href="%s">sources.json</a> · <a href="%s">listings.csv</a></p></section>' % (
                    self.u("/data/sources.json"), self.u("/data/listings.csv"))]
        return self.layout("Sources | Landosaur", "The official land sources Landosaur reads daily, when each was last read and how failures are handled.",
                           "/sources/", "".join(body), jsonld=[crumb_ld])

    def about(self):
        crumbs, crumb_ld = self.crumbs([("About", "/about/")])
        body = [crumbs, "<h1>About Landosaur</h1>", """
<p class="lede">Landosaur puts land that governments are selling on one map: city-owned vacant lots, tax-forfeited parcels and state land,
each with the facts the agency published, the date they were read and a link to the agency's own listing.</p>
<section><h2>Who it is for</h2><p>People looking for land the big portals rarely show: homesteaders, neighbours who want the lot next door,
small builders, gardeners and land investors comparing tax-sale and state offerings.</p></section>
<section><h2>What it is not</h2><p>Landosaur is not an offer to sell and does not sell, broker or hold any land. It is not affiliated with the agencies it lists.
It gives no legal, tax, title or investment advice and does not appraise land. Minimum bids are not sale prices. Tax-sale land can carry redemption rights,
title problems, liens and unknown condition; read the agency's terms and get professional advice before you bid or buy.</p></section>
<section><h2>This edition</h2><p>This is a static edition of Landosaur that updates itself every day from the official sources. The full application,
with accounts, saved worksheets and buying-help requests, runs at <a href="%s/" rel="noopener">%s</a>.
Land values per acre for every county are on the sister site, the <a href="%s/">US County Land Index</a>.</p></section>
<section><h2>Corrections</h2><p>If a listing is wrong or no longer available, the agency's page is authoritative. To report a problem with this site,
<a href="%s" rel="noopener">open an issue</a>.</p></section>
<section><h2>Privacy</h2><p>No accounts, no cookies, no tracking%s. The worksheet runs in your browser and sends nothing anywhere.</p></section>
""" % (esc(config.ORIGINAL_URL), esc(config.ORIGINAL_URL.split("://")[-1]), esc(config.LAND_INDEX_URL), esc(config.REPO_URL + "/issues"),
       " beyond a cookieless page counter" if config.GOATCOUNTER else "")]
        return self.layout("About | Landosaur", "Landosaur maps government and auction land offerings from official sources. Not an offer to sell; no advice.",
                           "/about/", "".join(body), jsonld=[crumb_ld])

    def data_page(self, files):
        crumbs, crumb_ld = self.crumbs([("Data", "/data/")])
        rows = "".join('<tr><th scope="row"><a href="%s">%s</a></th><td>%s</td></tr>' % (self.u(p), esc(p.rsplit("/", 1)[-1]), esc(d)) for p, d in files)
        body = [crumbs, "<h1>Data downloads</h1>", '<p class="lede">The same listings as files. Facts belong to the agencies that published them; '
                'check each agency\'s terms before reusing their data. The code and the compilation are open source.</p>',
                '<div class="scroll"><table class="data"><thead><tr><th scope="col">File</th><th scope="col">Contents</th></tr></thead><tbody>%s</tbody></table></div>' % rows,
                '<p>Feeds: <a href="%s">all new listings</a>, and one per state under <code>/feeds/</code>.</p>' % self.u("/feeds/new.xml")]
        return self.layout("Data downloads | Landosaur", "Download Landosaur's government land listings as CSV and JSON, with source status.",
                           "/data/", "".join(body), jsonld=[crumb_ld])

    def not_found(self):
        body = ('<h1>Page not found</h1><p class="lede">That page is not here. Listings that leave an agency\'s inventory are removed after two daily checks.</p>'
                '<p><a href="%s">Open the map</a> · <a href="%s">New listings</a></p>' % (self.u("/"), self.u("/new/")))
        return self.layout("Page not found | Landosaur", "This page does not exist.", "/404.html", body)
