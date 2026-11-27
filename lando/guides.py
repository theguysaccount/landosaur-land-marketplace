"""Source-cited Land Buyer Research Guides ported from data/research/*.md."""
import html
import json
import os
import re

from . import config

SOURCES = {
    "nass": ("USDA NASS: Land values methodology and quality measures", "https://www.nass.usda.gov/Publications/Methodology_and_Data_Quality/Land_Values/index.php"),
    "charts": ("USDA NASS: Land value charts and maps", "https://data.nass.usda.gov/Charts_and_Maps/Land_Values/index.php"),
    "units": ("NIST: General tables of units of measurement", "https://www.nist.gov/system/files/documents/2021/11/30/2022-HB44-Section-Appendix-C.pdf"),
    "feet": ("NIST: U.S. survey foot", "https://www.nist.gov/pml/us-surveyfoot"),
    "balloon": ("CFPB: What is a balloon payment?", "https://www.consumerfinance.gov/ask-cfpb/what-is-a-balloon-payment-when-is-one-allowed-en-104/"),
    "deed": ("CFPB: Contract for deed research report (2024)", "https://files.consumerfinance.gov/f/documents/cfpb_contract-for-deed_report_2024-08.pdf"),
    "construction": ("CFPB: Construction loan disclosure FAQs", "https://www.consumerfinance.gov/compliance/compliance-resources/mortgage-resources/tila-respa-integrated-disclosures/tila-respa-integrated-disclosure-faqs/"),
    "farmLoans": ("USDA FSA: Farm ownership loans", "https://www.fsa.usda.gov/resources/loans/farm-ownership-loans"),
    "alaska": ("Alaska DNR: Land sales frequently asked questions", "https://dnr.alaska.gov/mlw/landsales/info/faq/"),
    "access": ("Alaska DNR: Access to state land sale parcels", "https://dnr.alaska.gov/mlw/landsales/info/access/"),
    "title": ("Texas Department of Insurance: Title insurance FAQ", "https://www.tdi.texas.gov/title/titlefaqs.html"),
    "commitment": ("Texas Department of Insurance: Title insurance procedural rules", "https://www.tdi.texas.gov/title/titlem4a.html"),
    "zoning": ("King County: Zoning and other land-use factors", "https://kingcounty.gov/en/dept/local-services/buildings-property/local-services-permit-guide/permit-guide/zoning"),
    "legalLot": ("King County: Proof of legal lot", "https://cdn.kingcounty.gov/-/media/king-county/depts/local-services/permits/building-land-use-permits/l/legal-lot.pdf?hash=C8AB26AC7DE7FDD94CB20ED5FEB6811C&rev=880c254134224462b902c1ed5a790e7a"),
    "septic": ("EPA: Frequent questions on septic systems", "https://www.epa.gov/septic/frequent-questions-septic-systems"),
    "septicCare": ("EPA: How to care for your septic system", "https://www.epa.gov/septic/how-care-your-septic-system"),
    "wells": ("EPA: Private drinking water wells", "https://www.epa.gov/privatewells"),
    "wellTesting": ("EPA: Protect your home's water", "https://www.epa.gov/privatewells/protect-your-homes-water"),
    "survey": ("BLM: Official surveys in support of land acquisitions", "https://www.blm.gov/policy/ib-2024-034"),
    "cadastral": ("BLM: Cadastral survey tools", "https://www.blm.gov/programs/lands-and-realty/cadastral-survey/cadastral-tools"),
    "minerals": ("BLM: Leasing and development of split estate", "https://www.blm.gov/programs/energy-and-minerals/oil-and-gas/leasing/split-estate"),
    "mineralPatents": ("BLM: Stock Raising Homestead Act split estate", "https://www.blm.gov/programs/energy-and-minerals/mining-and-minerals/split-estate"),
    "flood": ("FEMA NFIP: Flood zones and maps", "https://www.floodsmart.gov/flood-zones-and-maps"),
    "floodMaps": ("FEMA NFIP: What are flood zones and maps?", "https://www.floodsmart.gov/flood-zones-and-maps/what-is-my-flood-zone"),
    "wetlands": ("U.S. Fish and Wildlife Service: Wetlands Mapper", "https://www.fws.gov/program/national-wetlands-inventory/wetlands-mapper"),
    "wetlandLaw": ("EPA: How wetlands are defined and identified under Section 404", "https://www.epa.gov/cwa-404/how-wetlands-are-defined-and-identified-under-cwa-section-404"),
    "soils": ("USDA NRCS: Web Soil Survey", "https://www.nrcs.usda.gov/resources/data-and-reports/web-soil-survey"),
    "slides": ("USGS: Landslide maps and susceptibility", "https://www.usgs.gov/programs/landslide-hazards/where-do-landslides-occur"),
    "taxSale": ("California State Controller: Chapter 7 tax sale FAQ", "https://www.sco.ca.gov/Files-ARD-Tax-Info/chapter7_faq.pdf"),
    "taxManual": ("California State Controller: County tax sale procedural manual", "https://sco.ca.gov/ardtax_tcs_taxguide.html"),
    "gsa": ("GSA: Real property disposition", "https://www.gsa.gov/real-estate/real-property-disposition"),
    "beginning": ("USDA: Building your farm business", "https://www.farmers.gov/your-business/beginning-farmers/build-knowledge"),
    "farmEconomics": ("Iowa State Extension: Evaluating a land purchase, economic analysis", "https://www.extension.iastate.edu/Agdm/wholefarm/html/c2-76.html"),
    "grazing": ("Colorado State Extension: Stocking rate estimation for cattle", "https://rangemanagement.extension.colostate.edu/online-calculators/stocking-rate-estimation-cattle/"),
    "timber": ("USDA Forest Service: What is my timber worth, and how do I sell it?", "https://www.srs.fs.usda.gov/econ/data/prices/wannano.htm"),
    "timberTax": ("USDA Forest Service: Timber tax tips for 2025", "https://research.fs.usda.gov/srs/articles/timber-tax-tips-2025"),
    "solar": ("Penn State Extension: Landowners guide to utility-scale solar leasing", "https://extension.psu.edu/pennsylvania-landowners-guide-to-utility-scale-solar-leasing"),
    "solarState": ("Pennsylvania DEP: Solar landowner resources", "https://www.pa.gov/agencies/dep/residents/solar-energy-resource-hub/landowner-resources"),
    "conservation": ("USDA NRCS: Agricultural land easements", "https://www.nrcs.usda.gov/programs-initiatives/ale-agricultural-land-easements"),
    "conservationTax": ("IRS Publication 526: Charitable contributions", "https://www.irs.gov/publications/p526"),
    "propertyTax": ("Texas Comptroller: Agricultural, timberland and wildlife special appraisal", "https://comptroller.texas.gov/taxes/property-tax/ag-timber/"),
}

GUIDES = [
    ("price-per-acre", "Price per acre is only the first comparison", "Prices & financing",
     "Compare gross acres, usable area and the total cost of making a parcel work.", "guide-price-per-acre.md", ("nass", "farmEconomics")),
    ("acre-size", "How big is an acre, really?", "Land fundamentals",
     "Translate acreage into dimensions without mistaking a map measurement for a surveyed boundary.", "guide-acre-size.md", ("units", "feet", "cadastral")),
    ("land-price-history", "Read land price history without inventing a trend", "Prices & financing",
     "Separate listing changes, recorded transfers and agricultural statistics before drawing conclusions.", "guide-land-price-history.md", ("nass", "charts")),
    ("cash-price-down-payment", "Cash price, down payment and opening bid", "Prices & financing",
     "Identify what an advertised number buys and compare complete payment schedules.", "guide-cash-price-down-payment.md", ("balloon", "alaska")),
    ("owner-financing", "Read an owner-financing offer before the payment", "Prices & financing",
     "Check deed timing, remaining debt, servicing and default terms before choosing seller financing.", "guide-owner-financing.md", ("deed", "balloon")),
    ("land-vs-construction-loans", "Land loans and construction loans fund different stages", "Prices & financing",
     "Plan the financing handoff from parcel acquisition to a completed, usable project.", "guide-land-vs-construction-loans.md", ("construction", "farmLoans")),
    ("legal-road-access", "A road on the map is not the whole access story", "Rights & buildability",
     "Trace the legal route, permitted uses and practical work needed to reach a property.", "guide-legal-road-access.md", ("access", "title")),
    ("zoning-buildability", "Is the parcel actually buildable?", "Rights & buildability",
     "Turn a zoning label into specific questions about legal lots, approvals and a feasible site layout.", "guide-zoning-buildability.md", ("zoning", "legalLot")),
    ("septic-feasibility", "Prove septic feasibility before choosing the homesite", "Site & environment",
     "Connect soil evaluation, design capacity, replacement area and permitting to the house you intend to build.", "guide-septic-feasibility.md", ("septic", "septicCare")),
    ("private-wells", "Evaluate a well as a water system", "Site & environment",
     "Review water rights, construction records, supply, quality and operating costs as separate questions.", "guide-private-wells.md", ("wells", "wellTesting")),
    ("boundary-surveys", "Order the survey that answers your decision", "Rights & buildability",
     "Define a useful survey scope and reconcile legal descriptions, monuments and visible occupation.", "guide-boundary-surveys.md", ("survey", "cadastral")),
    ("title-easements", "Read the title exceptions with the site plan", "Rights & buildability",
     "Understand which documents affect the land, what insurance covers and what remains unresolved.", "guide-title-easements.md", ("title", "commitment")),
    ("mineral-rights", "Surface ownership and mineral rights can be different", "Rights & buildability",
     "Identify reserved interests, existing leases and surface implications before assigning mineral value.", "guide-mineral-rights.md", ("minerals", "mineralPatents")),
    ("flood-risk", "Flood diligence beyond the map pin", "Site & environment",
     "Check the full parcel, access route, proposed improvements and cost of a workable design.", "guide-flood-risk.md", ("flood", "floodMaps")),
    ("wetlands", "Wetland screening is the start of a site decision", "Site & environment",
     "Separate inventory maps, field delineation and regulatory review before altering land.", "guide-wetlands.md", ("wetlands", "wetlandLaw")),
    ("soil-slope", "What soils and slopes change about your plan", "Site & environment",
     "Use terrain and soil evidence to target field work and test the cost of usable area.", "guide-soil-slope.md", ("soils", "slides")),
    ("tax-sales", "What you are buying at a tax sale", "Buying process",
     "Distinguish liens from deeds and investigate the exact rights, deadlines and remaining obligations.", "guide-tax-sales.md", ("taxSale", "taxManual")),
    ("land-auctions", "Set a land auction limit before the bidding starts", "Buying process",
     "Build a maximum bid from the total commitment and the sale's actual conditions.", "guide-land-auctions.md", ("alaska", "gsa")),
    ("homestead-feasibility", "Test a rural homestead as a complete system", "Land uses & ownership",
     "Connect year-round access, services, food production and time to a realistic first-year plan.", "guide-homestead-feasibility.md", ("beginning", "access", "wells")),
    ("farm-pasture-economics", "Separate farm business income from land income", "Land uses & ownership",
     "Use operating budgets, lease terms and forage capacity to judge agricultural land.", "guide-farm-pasture-economics.md", ("farmEconomics", "grazing")),
    ("timber-value", "Standing trees are not a timber valuation", "Land uses & ownership",
     "Connect a forest inventory to harvest constraints, local buyers and the property left afterward.", "guide-timber-value.md", ("timber", "timberTax")),
    ("solar-leases", "Screen solar potential before pricing a lease", "Land uses & ownership",
     "Evaluate grid access, the option period, operating rent and restoration obligations separately.", "guide-solar-leases.md", ("solar", "solarState")),
    ("conservation-easements", "Buy conservation land with the restrictions in view", "Land uses & ownership",
     "Read the recorded easement, permitted uses and long-term stewardship commitments.", "guide-conservation-easements.md", ("conservation", "conservationTax")),
    ("annual-ownership-costs", "Budget for the land after closing", "Land uses & ownership",
     "Build a seasonal ownership budget with taxes, maintenance, capital reserves and an exit scenario.", "guide-annual-ownership-costs.md", ("propertyTax", "septicCare")),
    ("buying-land", "A better way to buy land", "Field guides & strategy",
     "From your first shortlist to a permanent property file: the questions, evidence and professionals that make each step useful.", "buying-land.md", ("nass", "title")),
    ("valuation", "What is this land actually worth?", "Field guides & strategy",
     "Closed sales, current condition, use scenarios and the hidden costs behind an apparent discount.", "valuation.md", ("nass", "farmEconomics")),
    ("aggregation", "The land market is many markets", "Field guides & strategy",
     "Where listings live, how sources overlap, and why a directory is different from an integrated feed.", "aggregation.md", ()),
    ("landio", "What we learned from LANDIO", "Field guides & strategy",
     "A dated public-site audit separating observed features from opportunities for deeper evidence and execution.", "landio.md", ()),
    ("professional-work", "Make specialist land work worth doing", "Field guides & strategy",
     "Scope survey, title, soil and engineering work around real decisions and carry evidence into ownership.", "professional-work.md", ("survey", "title")),
]

INTERNAL_REMAP = {
    "/analyze": "/analyze/",
    "/services": "/sources/",
    "/land-prices": "/land-prices/",
    "/land-prices/history": "/land-prices/history/",
    "/land-prices/states": "/land-prices/states/",
    "/land-prices/cheapest-land-per-acre": "/land-prices/cheapest-land-per-acre/",
    "/land-prices/by-acreage": "/land-prices/by-acreage/",
    "/land-prices/data-methodology": "/land-prices/data-methodology/",
    "/land-for-sale": "/land-for-sale/",
    "/sources": "/sources/",
    "/research": "/research/",
    "/coverage": "/sources/",
    "/opportunities": "/closing-soon/",
    "/buying-help": "/research/buying-land/",
    "/sell": "/about/",
    "/workspace": "/analyze/",
}


def _rewrite_link(href, base_prefix):
    if href.startswith("http://") or href.startswith("https://"):
        return href, True
    clean = href.split("#")[0].split("?")[0]
    frag = "#" + href.split("#", 1)[1] if "#" in href else ""
    if clean in INTERNAL_REMAP:
        return base_prefix + INTERNAL_REMAP[clean] + frag, False
    if clean.startswith("/research/") and not clean.endswith("/"):
        return base_prefix + clean + "/" + frag, False
    if clean.startswith("/land-prices/") and not clean.endswith("/"):
        return base_prefix + clean + "/" + frag, False
    if clean.startswith("/"):
        target = clean if clean.endswith("/") else clean + "/"
        if target in ("/analyze/", "/land-prices/", "/land-for-sale/", "/research/", "/sources/", "/about/", "/data/", "/new/", "/closing-soon/"):
            return base_prefix + target + frag, False
        # Safe fallback for legacy app routes (e.g. /workspace/deals)
        return base_prefix + "/analyze/", False
    return href, False


def _inline_md(text, base_prefix):
    # Escape HTML first, then render links, bold, inline code, italics
    tokens = []

    def stash_link(m):
        lbl, href = m.group(1), m.group(2)
        url, external = _rewrite_link(href.strip(), base_prefix)
        rel = ' rel="noopener noreferrer"' if external else ""
        tokens.append('<a href="%s"%s>%s</a>' % (html.escape(url, quote=True), rel, html.escape(lbl)))
        return "\x00TOK%d\x00" % (len(tokens) - 1)

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", stash_link, text)
    out = html.escape(text)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"<em>\1</em>", out)
    for i, tok in enumerate(tokens):
        out = out.replace("\x00TOK%d\x00" % i, tok)
    return out


def markdown_to_html(md_text, base_prefix=""):
    """Convert Landosaur guide markdown (headings, paragraphs, lists, tables, blockquotes) to semantic HTML."""
    lines = md_text.splitlines()
    # Drop leading H1 since template renders the page H1
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    out = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("### "):
            out.append("<h3>%s</h3>" % _inline_md(line[4:].strip(), base_prefix))
            i += 1
        elif line.startswith("## "):
            out.append("<h2>%s</h2>" % _inline_md(line[3:].strip(), base_prefix))
            i += 1
        elif line.startswith("> "):
            q = []
            while i < n and lines[i].strip().startswith("> "):
                q.append(lines[i].strip()[2:])
                i += 1
            out.append('<blockquote class="callout">%s</blockquote>' % _inline_md(" ".join(q), base_prefix))
        elif line.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|?$", lines[i + 1].strip()):
            hdr = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            body_rows = []
            while i < n and lines[i].strip().startswith("|"):
                body_rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            th = "".join('<th scope="col">%s</th>' % _inline_md(c, base_prefix) for c in hdr)
            trs = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline_md(c, base_prefix) for c in r) for r in body_rows)
            out.append('<div class="scroll"><table class="data"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, trs))
        elif re.match(r"^[-*]\s+", line):
            items = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append("<li>%s</li>" % _inline_md(re.sub(r"^[-*]\s+", "", lines[i].strip()), base_prefix))
                i += 1
            out.append('<ul class="notes">%s</ul>' % "".join(items))
        elif re.match(r"^\d+\.\s+", line):
            items = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                items.append("<li>%s</li>" % _inline_md(re.sub(r"^\d+\.\s+", "", lines[i].strip()), base_prefix))
                i += 1
            out.append('<ol class="notes">%s</ol>' % "".join(items))
        else:
            para = []
            while i < n and lines[i].strip() and not re.match(r"^(#{2,3}\s|> |\||[-*]\s|\d+\.\s)", lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>%s</p>" % _inline_md(" ".join(para), base_prefix))
    return "\n".join(out)


def load_guides(data_dir=None, base_prefix=""):
    root = os.path.join(data_dir or config.DATA, "research")
    out = []
    for slug, title, category, description, filename, src_keys in GUIDES:
        path = os.path.join(root, filename)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        out.append({
            "slug": slug,
            "path": "/research/%s/" % slug,
            "title": title,
            "category": category,
            "description": description,
            "updated": "2026-10-01",
            "sources": [{"title": SOURCES[k][0], "url": SOURCES[k][1]} for k in src_keys if k in SOURCES],
            "body_html": markdown_to_html(raw, base_prefix),
        })
    state_path = os.path.join(root, "state-buying.json")
    if os.path.isfile(state_path):
        with open(state_path, encoding="utf-8") as fh:
            for guide in json.load(fh):
                slug = "buying-land-in-" + guide["slug"]
                out.append({
                    "slug": slug,
                    "path": "/research/%s/" % slug,
                    "title": "Buying Land in %s: Tax Sales and Due Diligence" % guide["name"],
                    "category": "State buying guides",
                    "description": guide["description"],
                    "updated": "2026-11-27",
                    "state": guide["state"],
                    "sources": [{"title": label, "url": url} for label, url in guide["sources"]],
                    "body_html": markdown_to_html(guide["body"], base_prefix),
                })
    return out
