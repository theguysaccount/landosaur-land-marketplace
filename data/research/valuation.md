# Land intelligence, valuation, and opportunity engine

Research date: October 1, 2026. Scope: United States first. This is a proposed product and technical design informed by current public primary sources, not an implemented model, live investment screen, appraisal, or independently tested vendor comparison. Vendor descriptions below are vendor claims; contracts and field-level samples remain to be obtained.

## The product to build

The strongest product is a **parcel evidence file plus a defensible valuation range plus a path to completing the transaction**. A number on a map is already available elsewhere. The opportunity is to show which information supports the estimate, which facts could invalidate it, what it would cost to resolve those facts, and whether the apparent discount survives the full cost of ownership and resale.

Each listing should answer six questions:

1. What exact property and ownership interest is offered, and is it still available?
2. What can a buyer plausibly do with it today, and what requires a permit, easement, infrastructure, or change in entitlement?
3. What did genuinely similar properties actually sell for?
4. What range of prices does the evidence support, and how reliable is that range in this market?
5. What are the acquisition, diligence, improvement, holding, financing, and selling costs?
6. Which unresolved item matters most, and who can resolve it?

The consumer result is a useful discovery tool. The professional result is a shared underwriting workspace. The accumulated, consented closing outcomes, professional corrections, and cost quotes can improve future decisions.

## Test the thesis rather than build its conclusion into the model

There is credible evidence of thin agricultural transaction markets. A USDA ERS study published in March 2025 estimated annual acreage turnover in the contiguous United States during **2019–2020** at **0.72% for cropland and 0.61% for pastureland**. It excluded non-arm's-length transactions and could not include 2021 because transaction data were incomplete. Its land classification also used a 2020 crop layer to classify older sales. These are historical agricultural estimates, not current turnover for every land type. [USDA ERS, tables 3.1–3.2 and methodology, printed pp. 44–47](https://www.ers.usda.gov/sites/default/files/_laserfiche/publications/111215/EIB-280.pdf?v=85314).

That supports a thesis of limited price discovery in some land markets. It does **not** establish that land is the world's most undertraded or most underpriced asset. Low turnover can reflect long ownership horizons, productive use, family transfer, or illiquidity; it does not itself prove a bargain. A worldwide ranking would require comparable asset universes, turnover definitions, and risk-adjusted valuation benchmarks that this research has not established.

The stronger company thesis is: **land is heterogeneous, information is fragmented, and costly uncertainty prevents some valuable matches between land and buyers. Better evidence and execution can lower that uncertainty.** This is a business hypothesis to measure.

Use regional land-value series as context, never as parcel appraisals. USDA's 2025 survey reported national cropland value of $5,830 per acre and pastureland of $1,920, while cropland state averages ranged from $1,320 in Montana to $32,900 in Rhode Island. Those differences alone make a universal dollars-per-acre screen misleading. [USDA NASS 2025 highlights](https://data.nass.usda.gov/Publications/Highlights/2025/2025LandValuesCashRents_FINAL.pdf). The survey covers qualifying farms and ranches in the contiguous 48 states; it is not a database of verified individual closing prices. [NASS methodology](https://data.nass.usda.gov/Publications/Methodology_and_Data_Quality/Land_Values/09_2025/landqm25.pdf).

## What is already on the market

| Platform | Publicly documented capability | Strategic implication |
|---|---|---|
| Regrid | National parcel API, parcel geometry, ownership and attributes; separate field-level coverage information | Buy and normalize foundational data before attempting to collect every county yourself. National geometry coverage is not complete sales, zoning, title, or utility coverage. [API](https://regrid.com/api), [schema and coverage](https://support.regrid.com/docs/regrid-parcel-schemas) |
| ATTOM | Property, ownership, tax, deeds, mortgages, geospatial and other enrichment; APIs and bulk/cloud delivery | Evaluate as a transaction/history backbone. Its broad property counts do not establish the quality of vacant-land comps in a target county. [Data foundation](https://www.attomdata.com/about-us/attom-difference/), [API](https://www.attomdata.com/solutions/delivery/property-data-api/) |
| Cotality, formerly CoreLogic | Property datasets delivered through API, bulk, cloud and interfaces; sales/ownership categories; MLS access through local providers | Candidate transaction and property source. MLS distribution and public-record licensing are distinct products and rights. [Data library](https://www.cotality.com/data-library), [delivery](https://www.cotality.com/our-data), [real estate access](https://www.cotality.com/industries/real-estate) |
| LightBox | Connected parcel, address, structure, assessment and zoning data; API options | Strong alternate backbone, particularly for development workflows. Verify parcel-level zoning depth locally. [SmartFabric](https://developer.lightboxre.com/solutions/smart-fabric), [zoning API](https://developer.lightboxre.com/apis/zoning) |
| Acres | Land comps, ownership/debt links, map layers, property reports, lead lists, site planning and shared portfolios | This is an existing professional land workspace competitor, not simply a listing site. Its sales database distinguishes courthouse, staff-curated, contributory and private comps. [Enterprise](https://www.acres.com/enterprise), [sales sources](https://support.acres.com/filter-comparable-sales-data) |
| AcreValue | Parcel and sales research, automated valuation where available, reports and bulk-data purchasing | A land AVM alone is not differentiated. Its bulk export product is a candidate partnership path; ordinary subscriptions do not establish redistribution rights. [Plans/features](https://www.acrevalue.com/pro/), [bulk data](https://www.acrevalue.com/bulk-data/parcels/) |
| Land id | Property research, map layers, media-rich branded property maps and embeds | Treat property presentation and collaboration as existing category expectations. [Product platforms](https://web.id.land/product-platforms) |
| Zoneomics | Zoning data APIs, including requests for uncovered areas and specific regulatory fields | Zoning coverage must be checked jurisdiction by jurisdiction. [Coverage request documentation](https://www.zoneomics.com/api-documentation/request) |

No general enterprise redistribution/model-training prices were verified for this scope. Obtain a written quote and rights schedule based on the actual product; do not use consumer subscription prices as the platform's data budget. Acres' public pages also state different total transaction counts, so neither number should be presented as an independently reconciled coverage figure.

## The evidence model

Build a permanent internal parcel identifier with a history graph. Preserve source parcel identifiers, county/FIPS, APN normalization, source geometry, geometry date, split/merge lineage and match confidence. A listing is an offer; it can contain multiple parcels, only part of a parcel, an undivided interest, a lease, or an assignment. A parcel can have many simultaneous listings. A sale can transfer many parcels. These must be different objects.

Keep these monetary concepts in different fields and interfaces:

- Asking cash price, asking financed price, down payment, installment, balloon and total financed payment.
- Auction starting bid, reserve if disclosed, current bid, buyer premium and reported final price.
- Verified gross sale consideration, concessions, cash-equivalent adjustment, sale date and recording date.
- Assessed, taxable, assessor-market, agricultural-use and land-only assessed values, each with tax year and local definition.
- Model-estimated current as-is value, proposed future project value, and verified professional appraisal.

Regrid explicitly cautions that very low recorded prices can be administrative transfers and that assessed value types differ by jurisdiction. Its deeded acreage, county acreage and calculated geometry acreage are also distinct. [Sales fields](https://support.regrid.com/docs/sales-transfers), [assessment fields](https://support.regrid.com/docs/assessment-tax), [acreage fields](https://support.regrid.com/docs/parcel-geometry-area-fields).

Every material fact should carry: source URL/document, provider and underlying authority, observed date, effective date, ingestion time, license scope, parcel/geometry version, extraction method, confidence, reviewer state and supersession history. Documents should be immutable with hashes; corrected fields must not erase the historical source. Use explicit states: **verified, seller-reported, third-party reported, inferred, unknown, conflicted, expired**. Unknown is not false and not safe.

## Obtaining sold evidence

Prioritize a licensed deed/transaction backbone, local assessor/recorder records, authorized MLS sold feeds, auction results with identified final-price status, and broker/appraiser/closing contributions with explicit permission. Cross-check the same transaction across sources rather than count duplicates as extra comps.

Separate data acquisition rights from display, caching, resale, derivative estimates, machine-learning training, sublicensing and post-termination retention rights. A vendor may let a customer export a report while prohibiting public redistribution of its underlying records. Acres, for example, documents export limits and separates private comps from contributory ones. [Acres exports](https://support.acres.com/exports).

Non-disclosure markets require special handling. Texas REALTORS explains that non-disclosure does not prohibit all disclosure or eliminate MLS reporting; local MLS rules govern permitted downstream use of sold prices. This is not a license to republish them. [Texas REALTORS, updated September 17, 2025](https://www.texasrealestate.com/legal-and-ethics/legal-resources/legal-faqs/professional-standards). Harris Central Appraisal District documents that its transaction sample is limited because mandatory sales disclosure is absent. [HCAD 2024 mass appraisal report](https://hcad.org/assets/uploads/pdf/Reports/MAR-2024-Final.pdf).

Do not convert loan principal into a sale price. Do not infer a land-only closing price by subtracting assessed building value from an improved-property sale without a separately validated allocation method. Do not attach the full consideration for a ten-parcel sale to each parcel. IAAO's sales-validation standard specifically calls for investigation of multi-parcel transactions and preservation of property characteristics as of sale. [IAAO sales verification standard](https://www.iaao.org/wp-content/uploads/Standard_on_Verification_Adjustment_of_Sales.pdf).

Suggested transaction quality hierarchy:

1. Verified closing/settlement or confirmed arm's-length sale with price, rights, parcel set and terms resolved.
2. Recorded sale with credible price and resolved parcel match; conditions not completely verified.
3. Licensed contributed comp with documented provenance and permission.
4. Reported sold event without verified price or terms: evidence of activity, not a price-training target.
5. Asking price, starting bid, tax assessment or automated estimate: separate context, never ground-truth sale price.

## Parcel diligence layers and their limits

| Layer | Source/use | Product rule |
|---|---|---|
| Parcel boundary and ownership | Licensed backbone plus current county/recorder cross-check | A GIS line is not a boundary survey; owner record is not a title opinion. Show conflicts and date. |
| Legal access | Recorded deeds, easements, title commitment, survey; local roads and highway authority | Nearby road geometry or a visible dirt track does not establish a transferable right of access. Record legal and physical access separately. |
| Zoning and entitlements | Authoritative ordinance and zoning map, planning staff/permit history; licensed normalized feed for discovery | Check overlays, minimum lot sizes, frontage, setbacks, special uses, subdivision and vesting. A zoning label alone cannot determine buildability. |
| Flood | Effective FEMA NFHL/FIRM and local floodplain studies; additional models as separately labeled risk estimates | Calculate polygon overlap, floodway exposure and access-route exposure. No mapped high-risk overlap does not mean no flood risk. [FEMA NFHL guidance](https://www.fema.gov/sites/default/files/documents/fema_national-flood-hazard-layer_112022.pdf), [NFIP risk explanation](https://www.floodsmart.gov/know-your-risk) |
| Wetlands | USFWS National Wetlands Inventory | A screening layer; the agency states its biological mapping does not determine the presence, absence or extent of legally regulated wetlands. [NWI mapper](https://www.fws.gov/program/national-wetlands-inventory/wetlands-mapper) |
| Soil/productivity/septic screening | NRCS SSURGO/gSSURGO and local health/soil tests | Soil map units include multiple components. Use them for screening; no automatic perc-pass or septic permit claim. [SSURGO](https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo), [onsite-investigation guidance](https://www.nrcs.usda.gov/sites/default/files/2022-11/from-the-surface-down.pdf) |
| Terrain | USGS 3DEP DEM/lidar | Derive slope distribution and contiguous suitable area, with resolution and collection date; not a grading quote. USGS makes 3DEP data available without charge/use restrictions. [3DEP](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services) |
| Crops and cover | NASS CDL and USGS Annual NLCD | Use historical polygon-weighted areas, accuracy flags and imagery dates. Neither proves current crop yield, vacant status, harvestable timber volume or a legal use. [CDL accuracy/access](https://www.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php), [Annual NLCD](https://www.usgs.gov/centers/eros/science/annual-national-land-cover-database) |
| Environmental concerns | EPA ECHO and relevant federal/state cleanup records; environmental professional review | Proximity is a screening signal, not proof of contamination. Absence of a database record is not a clean-site finding. [ECHO services](https://echo.epa.gov/tools/web-services) |
| Habitat and protected areas | USFWS IPaC and USGS PAD-US; authoritative easement documents | IPaC distinguishes informal screening lists from official species lists. Protected-area geometry does not fully describe a recorded easement's terms. [IPaC](https://ipac.ecosphere.fws.gov/), [PAD-US](https://www.usgs.gov/tools/pad-us-data-explorer) |
| Water | State/local well logs, water-right records, water districts; USGS monitoring | A nearby functioning well does not guarantee this parcel's water yield, right or permit. Use modern APIs; legacy USGS WaterServices are scheduled for retirement in early 2027. [USGS water API](https://www.usgs.gov/tools/usgs-water-data-apis) |
| Electricity/other utilities | Provider service-area maps plus parcel-specific will-serve/capacity/extension quotes | Distance to infrastructure is not connection entitlement, capacity or cost. Public transmission maps are screening context only. [EIA infrastructure data FAQ](https://www.eia.gov/tools/faqs/faq.php?id=567&t=3) |
| Taxes and carrying restrictions | County tax bill, special assessments, agricultural treatment/rollback analysis, HOA/POA/CC&Rs | Current owner's bill is not necessarily buyer's post-closing bill. Obtain use-change implications locally. |
| Mineral, timber and water rights | Deed/title, reservation and lease instruments, specialist review | Surface ownership does not establish that every valuable right is included. Explicitly model the conveyed interest. |

Calculate geometric constraints on the parcel polygon, not only its centroid. Overlay intersections must be unioned before calculating constrained acres; otherwise flood/wetland/slope overlaps get subtracted multiple times. "Potentially suitable contiguous acres" is a screening output; reserve "approved buildable area" for the relevant professional/authority evidence.

## Valuation architecture by land type

Start with separate models for comparable economic uses and rights. A mixed-use parcel can have components, but avoid double-counting a speculative development premium and an agricultural value representing the same future period.

| Segment | Primary valuation approach | Essential distinctions |
|---|---|---|
| Rural residential/homesite | Matched sold comps and nonlinear hedonic model | Legal/physical access, septic/water path, utilities, entitlement, shape, terrain, size discount, travel time, view/waterfront, restrictions |
| Cropland | Local sale model plus net-rent/income cross-check | Tillable and irrigated acres, soil productivity, water rights/reliability, drainage, lease, improvements, commodity region; gross rent is not NOI |
| Ranch/pasture | Comparable sales plus sustainable income cross-check | Carrying capacity, water, fencing, access, forage, improvements, lease/permit terms; public grazing permits are not fee acres |
| Timberland | Land value plus discounted timber cash flows, reconciled against sales | Cruise inventory, species, age, stocking, harvest costs, roads, mills, fire exposure; distinguish bare land from standing timber |
| Recreational/conservation | Use-matched comps and evidenced lease income where relevant | Legal access, habitat, water, adjacency, seasonality, restrictions; conservation restrictions can narrow use while preserving particular value |
| Infill/entitled development | Land sales plus residual development value/DCF | Approved units/floor area, absorption, utilities, fees, site works, construction, timing, financing, contingency and developer return |
| Speculative development | Current-use value plus separately modeled entitlement scenarios | No assumption that rezoning, subdivision, sewer extension or annexation will happen; probability and cost evidence required |
| Energy/industrial | Rights- and use-specific sales/lease DCF | Interconnection, delivered capacity, queue/study status, access and permitting; distance to a power line is insufficient |

Recommended model stack (design proposal):

- **Transparent baseline:** nearest comparable sales filtered by rights/use and adjusted with locally supportable size, time and physical differences. Show the comp selection and exclusion reasons.
- **Predictive model:** segment-level gradient boosting or hierarchical hedonic model using log total transaction value, nonlinear size effects, geographic interactions and time. Do not force constant dollars per acre. Use spatially local models only where sample size justifies them; partially pool sparse regions.
- **Independent economic check:** net-income capitalization or discounted cash flow for appropriate segments. Cap rates, costs and absorption must be locally evidenced or labeled assumptions.
- **Reconciliation:** combine models only after out-of-sample evaluation. Disagreement is a reason to widen the interval or request review, not average blindly.
- **Language model role:** extract and cite structured claims from documents, assist comp explanations and ask for missing inputs. Never let unsupported generated prose create title, access, permit or value facts.

For residual development value, compute discounted realizable project receipts minus discounted non-land project costs and an explicit risk/return treatment. Do not subtract a full developer-profit allowance and also use a discount rate containing the same profit requirement without explaining the convention. Show current as-is value and scenario-specific future value separately.

## What the calculator should show

Minimum output for an eligible parcel:

- Valuation date, exact interest/parcel set, intended use and "as-is" assumptions.
- Median estimate and empirically calibrated prediction range; sensible rounding rather than dollar-level precision.
- Comp count, effective weighted sample size, newest/oldest sale, maximum distance and segment similarity.
- Each comp's price verification level and adjustments, with source links subject to license.
- Model version and historical performance for the relevant segment/geography/price band.
- Asking cash-equivalent price, asking-price discount, conservative net acquisition margin and holding-time scenarios.
- Top missing facts and sensitivity to changing each one.
- Explicit "insufficient evidence to estimate" state when key facts or comparable support fail.

Do not present an estimated 80% range as a property-specific guarantee. Coverage is an empirical statement about similar evaluated cases, conditional on the population and assumptions. A tight-looking range from the wrong segment is not trustworthy.

## An opportunity ranking that survives actual costs

Offer separate sorts: **lowest cash price**, **lowest price per relevant usable unit**, **largest estimated discount**, and **strongest conservative margin**. These answer different questions. A cheap parcel can be correctly priced, while a high-priced parcel can be attractive relative to its realistic uses.

For a simple unlevered resale screen at one stated horizon T:

`All-in cash cost = purchase price + acquisition/diligence costs + scenario-specific works + carrying costs through T`

`Net exit proceeds = scenario exit sale price − selling costs`

`Conservative margin dollars = conservative net exit proceeds − all-in cash cost`

`Conservative margin % of cost = conservative margin dollars / all-in cash cost`

For irregular timing, use dated cash flows and NPV/IRR; do not present a simple margin as an annual return. Keep levered and unlevered views separate. A financing model includes the applicable interest/fees and principal repayment, without counting borrowed principal as income.

Use a conservative jointly simulated scenario for exit price, time and costs. Subtracting independent worst cases can be excessively pessimistic; subtracting unrelated expected values can miss correlated downside. Either approach must identify its assumptions. Avoid charging for a defect twice: if the exit value already assumes the property is sold with that defect, do not deduct a hypothetical cure cost unless the scenario actually includes curing it.

Rank eligible parcels using conservative NPV or margin, downside-loss probability, liquidity evidence and buyer fit. Show those dimensions, not just an unexplained 97/100. Sponsored placement must never alter the valuation or opportunity ranking. Unverified access/title/availability should move a parcel into a **research queue**, not allow it to win the bargain leaderboard through a nominal penalty.

### Worked hypothetical: the apparent 40% discount

This example is invented to demonstrate the calculation; it is not a real listing or forecast. Assume verified parcel identity/access and a resale of the same rights in twelve months, with no change of use.

| Item | Amount |
|---|---:|
| Asking cash price | $60,000 |
| Modeled twelve-month gross resale median | $100,000 |
| Modeled twelve-month conservative gross resale scenario | $80,000 |
| Acquisition, survey and diligence | $4,000 |
| Required site/access maintenance in this scenario | $8,000 |
| Twelve-month taxes, insurance and other carrying costs | $5,000 |
| Selling cost assumption | 8% of resale price |

The headline asking-price discount to the modeled median is 40%. All-in cash cost is $77,000. Median net exit is $92,000, leaving $15,000 or 19.5% of cost before income taxes. Conservative net exit is $73,600, leaving **negative $3,400, or −4.4%**. At a longer sale time or with an added utility obligation, it worsens. The product should show that discrepancy prominently. If the $100,000 estimate actually assumes installed utilities that this parcel lacks, the comp/model must be corrected before either margin is meaningful.

## Training, evaluation, and release controls

Design the evaluation before selecting the algorithm.

1. Maintain a dated, immutable sale-label store. Validate arm's-length status, conveyed rights, parcel grouping, terms and property state at sale. Sample audits must include extremely cheap deals, not only typical transactions.
2. Train on information available at the historical valuation time. Today's zoning, later improvement permits and sale-derived assessed values can leak the answer. Keep listing price out of the primary independent-value model; evaluate it separately in an explicitly disclosed asking-price-aware model if useful.
3. Split by time and geographic groups. Deduplicate before splitting and keep related parcel splits, repeat transactions and subdivisions in appropriate groups. Random row splits alone will overstate performance when near-duplicate or nearby properties leak across sets.
4. Benchmark against local median/size-adjusted comps and professional review. Report median absolute percentage error, median log error, dollar MAE, signed bias and proportions within 10/20/30% of later observed prices. Percentage error becomes unstable on very low-dollar sales, so inspect those cohorts separately.
5. Evaluate by segment, county/market, acreage, price, comp density, data age and non-disclosure status. Report sample sizes and bootstrap confidence intervals; do not claim a national accuracy based only on easy markets.
6. Calibrate prediction intervals on held-out data; test 80% and 90% coverage and width. Conformal methods can help, but spatial clustering and market change violate simple exchangeability assumptions; validate rolling and regional coverage rather than promise distribution-free certainty for every parcel.
7. Test the bargain screen itself: expert-confirmed precision among top-ranked candidates, false-cheap reasons, expected-vs-realized costs and time, and outcomes of unsold/withdrawn listings. Sale-only evaluation is selected and must not be represented as all-inventory reliability.
8. Track stale listings, re-listing continuity, withdrawn sales and right-censoring for time-to-sale estimates. Absence of a closing is not a zero price; a removed listing is not automatically a sale.
9. Independent reviewers can correct facts with evidence, but sales staff must not tune estimates to satisfy sellers. Keep overrides, appeals and model changes auditable. Evaluate systematic error across relevant market groups and avoid protected personal characteristics in valuation or opportunity targeting.
10. Use model cards and release gates. Abstain when evidence is inadequate; freeze or roll back a model when coverage, drift or local calibration fails.

IAAO's AVM standard discusses independent quality assessment, ratio dispersion, bias and statistical uncertainty; it is a useful professional reference, not proof that this proposed model meets it. [IAAO AVM standard](https://www.iaao.org/media/standards/Standard_on_Automated_Valuation_Models.pdf). If entering mortgage collateral workflows, separately determine applicable requirements: the federal AVM rule addresses specified mortgage uses involving a consumer's principal dwelling and should not be casually described as a universal rule for every vacant-land estimate. [FHFA rule explanation](https://www.fhfa.gov/news/news-release/agencies-issue-final-rule-to-help-ensure-credibility-and-integrity-of-automated-valuation-models).

Suggested pilot acceptance criteria are **proposals, not achieved results**: 100% of published estimates retain provenance/model version; no missing legal-access field is shown as verified access; predeclared accuracy/interval targets pass in supported cohorts; every top-tier opportunity receives a documented review; unsupported cohorts display no estimate. Choose numeric error targets after an initial independent benchmark and customer tolerance study rather than invent a universal accuracy promise.

## Procurement and the first validation experiment

Run a fixed-sample vendor bake-off before buying national redistribution rights. Select several counties representing a sale-disclosure rural market, a non-disclosure market, a development fringe and a sparse recreational market. Use the same stratified parcel/sale sample across vendors and independently verify a subset with authorized local records and professionals.

Score: parcel match/geometry quality; sale-price correctness; transfer-vs-sale classification; bundle allocation; sale/recording dates; attribute state as of sale; freshness; field-level missingness; licensing; permitted outputs; service reliability; and cost per usable verified comp. More rows is not automatically better. Ask for record-level lineage and confidence, not only a national coverage percentage.

A sensible first paid product is **expert-reviewed land opportunity reports and a shared diligence workspace in a limited set of counties**. Start the model with ordinary un-improved rural parcels in one clearly defined buyer/use segment. Add farmland, development and timber modules after proving each data and valuation method. In parallel, provide useful search everywhere, but label where automated estimates are unsupported.

The feedback flywheel is: authorized listing → identified parcel/rights → evidence and comps → professional diligence and cost quotes → recorded decision → consented closing outcome → audited model improvement. Its strongest defensibility comes from difficult-to-obtain verified outcomes and workflow adoption, not from claiming to have the most layers.
