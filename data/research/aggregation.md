# Land listing supply and aggregation research

Research date: 2026-10-01. US first; international expansion map included. Prepared for the land super-site scoping study.

## What this inventory contains

The accompanying `land-listing-sources.csv` contains **135 source/access-route records across 135 normalized hostnames**:

- **126 listing-source records**: **90 verified through an official source page, live browser review, or official indexed search result**, and **36 discovery candidates** needing further validation.
- **9 separately labeled data suppliers, delivery routes, or standards organizations**: 8 verified offerings and 1 candidate. These are **not counted as land listing websites**.
- Across the full file: **98 verified official offerings, 37 candidates, zero contracted feeds, zero integrations**.

“Verified” means the official source's relevant offering was observed in this research. It does not verify every listing, seller, inventory count, claim, boundary, title, coverage, permission, or ability to export data. Some verification used search-engine text of an official page when direct retrieval was unavailable. A failed retrieval is not proof a business is defunct. Candidate records are a clearly marked research queue, not confirmed active land supply. Dates on cached/indexed content can lag the research date.

This is a broad starting universe, not “every website.” No finite desk-research pass establishes completeness across local brokers, county auctions, municipalities, private exchanges, social groups, global portals, and off-market sellers. Hostnames are not independent companies, and company count is not unique parcel count. Parent families and likely syndication overlap are recorded; ownership is not exhaustively audited.

| Category | Source records |
|---|---:|
| US specialist land portals | 15 |
| US general/commercial portals | 10 |
| US land brokers and managers | 30 |
| US direct sellers / owner finance | 15 |
| US auctions and distressed sources | 14 |
| US government and land banks | 14 |
| Land leases and access | 7 |
| International listing sources | 21 |
| Data delivery / enrichment / standards, not listing sites | 9 |

Priority is a proposed business-development order, not a statement about confirmed access: P1 = first partnership/coverage work; P2 = segment or regional expansion; P3 = long tail, higher operational friction, or later international work. Commercial terms and seller authorization remain unverified unless explicitly described as an official program offering.

## The most useful aggregation conclusion

**Build an authorized, parcel-centered supply network. A giant portal scraper is a weak foundation.** The original broker, owner, auctioneer, or public agency is often the better source of truth than the site that republishes its listing. Win direct supply through useful seller tools, then supplement it with licensed distribution feeds and authorized public notices.

The best first acquisition route found is [ListHub's publisher offering](https://www.listhub.com/): its official site describes a publisher API covering hundreds of MLS sources under one contract and says broker sponsorship is not required. This is evidence of a commercial route to investigate, not an agreement granting this project access. Confirm vacant-land coverage, broker opt-ins, geographic exclusions, required attribution, allowed analytics, historical retention, and training rights. A single publisher agreement may reduce connector work more than dozens of portal-specific deals.

[MLS Grid](https://www.mlsgrid.com/) offers a standardized licensed feed and compliance framework for approved vendors. It is a second concrete route, with eligibility and member-market coverage to establish. [RESO](https://www.reso.org/reso-web-api/) supplies standards, not the MLS inventory itself. Technical compatibility does not create data rights.

A crucial trap: [LandSearch's feed program](https://www.landsearch.com/feed) is **inbound XML ingestion into LandSearch**. It does not establish an API to export all LandSearch inventory. Its [terms](https://www.landsearch.com/corp/terms) address automated extraction; any competing republication use needs express negotiated rights. Keep inbound syndication, outbound licensing, public indexing, model training, and display rights as separate fields in the source contract registry.

## Supply families that must not be double-counted

- [Land.com](https://www.land.com/), [LandWatch](https://www.landwatch.com/), and [Land And Farm](https://www.landandfarm.com/) are the CoStar Land.com Network. Their websites are useful separate discovery surfaces, but negotiating and measuring them as three unrelated inventories would inflate coverage. [Lands of America](https://landsofamerica.com/) redirected to Land.com during this research and is excluded as an additional source row.
- [LANDFLIP](https://www.landflip.com/) explicitly links FARMFLIP, RANCHFLIP, LOTFLIP, and AUCTIONFLIP as its network. Treat category sites as views over potentially overlapping supply. LANDTHINK is editorial content and is excluded from listing-source counts.
- [Whitetail Properties](https://www.whitetailproperties.com/) links its [Ranch and Farm Auctions](https://ranchandfarmauctions.com/) operation. Listings and auction events can describe the same parcel at different stages.
- [Farmers National Company](https://www.farmersnational.com/) operates [Hunting Lease Network](https://www.huntingleasenetwork.com/). It also [announced acquiring CommonGround on September 15, 2026](https://www.farmersnational.com/news/fnc-news/fnc-commonground-acquisition). Their land sales, farm management, farmland leases, and hunting leases are different products within a related group.
- National broker networks, their local franchise/member sites, MLS portals, and specialist marketplaces may all publish the same listing. LandLeader and its member brokerages particularly need origin-level lineage. Do not assume every network-owned or syndicated listing has identical reuse permissions.

A separate caution on currency: `landstore.com` redirected to an Atom domain-for-sale page in this research. It is excluded. Historical roundup lists can silently contain dead domains, renamed companies, editorial websites, or duplicates.

## Where overlooked supply is most likely

**Specialist broker direct relationships.** National Land Realty, Whitetail, Mossy Oak, Hayden Outdoors, United Country, Hall and Hall, Fay Ranches, LandLeader, and regional specialists provide useful initial density. Regional brokers add land knowledge, documents, ownership contact, and sold evidence that portal republication may lose. Obtain only content the broker is entitled to authorize: [National Land Realty's official page](https://nationalland.com/) distinguishes third-party MLS/IDX material in its notices.

**Farm and timber managers.** [Farmers National](https://www.farmersnational.com/), [Peoples Company](https://peoplescompany.com/), [AFM Real Estate](https://www.afmrealestate.com/), [LandVest](https://landvest.com/), [Fountains Land](https://fountainsland.com/), and [Saunders](https://www.saundersrealestate.com/) connect listings to income, forestry, appraisals, and management. These are particularly valuable to a company selling B2B analysis and ongoing ownership services.

**Direct sellers and owner financing.** LandCentral, Classic Country Land, Compass Land USA, Land Elevated, BillyLand, LandZero, InstantAcres, OzarkLand, and Christmas and Associates give access to a different affordability funnel. [Compass Land USA](https://www.compasslandusa.com/) illustrates why a price schema must separate cash price, down payment, and financing; its own site presents these distinctly. Seller claims still require independent diligence.

**Government and land banks.** [Alaska DNR](https://dnr.alaska.gov/mlw/landsales/) separates OTC, resident auction, and agricultural programs with different eligibility. [Michigan DNR](https://www.dnr.state.mi.us/LandSale/) includes post-auction direct sales. [California DGS](https://www.dgs.ca.gov/RESD/Resources/DGS-Real-Estate-Surplus-Property) distinguishes surplus sales and lease opportunities. [Detroit Land Bank](https://buildingdetroit.org/) offers vacant-lot programs with adjacency and program conditions. A low sticker price under a restricted program is not equivalent to an unrestricted market bargain. [BLM](https://www.blm.gov/programs/lands-and-realty/sales-and-exchanges) says sales concern selected parcels under its land-use process; public ownership is not evidence land is for sale.

**Auctions.** Bid4Assets county programs, Tax-Sale.info, Schrader, Steffes, Ranch and Farm Auctions, and Williams and Williams extend supply beyond ordinary broker search. Auctions need event/tract modeling, bid deadlines, deposits, reserve status, buyer premium, redemption rights, title conditions, and final result handling. Opening bid is not an asking price or fair market value.

**Leases and use rights.** CommonGround, Hunting Lease Network, Base Camp Leasing, HLRBO, and LandTrust suggest a broader land business than buying and selling acreage. Agricultural rent, seasonal hunting rights, and short access bookings must have separate schemas and search tabs; they are not comparable sale prices.

**International.** The file includes UK, Canada, Australia, New Zealand, Spain, France, South Africa, India, Mexico, and international luxury portals. Expand one legal/registry environment at a time. Currency and acreage conversion are the easy part; tenure, title systems, cadastral identity, foreign-buyer restrictions, planning permission, and local brokerage rights require country-specific work.

## Recommended first supply program

This is a proposed operating plan, not work already contracted.

1. **Obtain one publisher data license and measure actual land density.** Start with ListHub commercial diligence, then MLS Grid/other permitted MLS routes for gaps. Require sample data under appropriate terms before estimating coverage.
2. **Recruit 10–20 original land suppliers in one launch region.** Offer upload, CRM import, document room, parcel-boundary review, qualified inquiries, pricing feedback, and syndication reporting. The software should create a reason to give the company fresh authorized inventory.
3. **Add 3–5 government or auction sources with written data terms.** Preserve official notice links and program restrictions; do not generalize a permission from one jurisdiction to another.
4. **Provide owner submission with identity, ownership/representation, and parcel checks.** Confirm authority to publish, images/documents ownership, status update obligations, and takedown path.
5. **Negotiate specialist portals selectively.** Land.com-family access could be valuable but should not be an assumed prerequisite. A competing portal may decline a feed license.
6. **Track incremental parcels, not impressive source counts.** A source gets credit for fresh unique usable supply, not duplicate syndication volume.

For a pilot, choose a tractable land type and a small connected region after inspecting actual licensed coverage. Avoid deciding national valuation accuracy from a national listing count.

## Required source and parcel contract

Maintain three entities: **parcel**, **listing**, and **listing-source observation**. A fourth entity, **sale/lease/auction event**, avoids destroying history when one parcel changes transaction mode.

Minimum fields include source and origin IDs; source URL; lawful-use basis; contract version; permitted fields/media/analytics/training; update and deletion obligations; origin brokerage/seller; jurisdiction plus normalized APN; geometry and its provenance; multi-parcel membership; asking cash price; financing down payment and total terms; auction bid/reserve/premium; rights being sold; deeded versus leased acreage; list/status dates; first seen/last seen/source updated; withdrawn/sold date; broker-confirmed status; and conflict flags.

Deduplicate with jurisdiction/APN first, geometry overlap second, then location/acreage/seller/listing text and media fingerprints as supporting evidence where licensed. A parcel split, assemblage, multiple tract auction, or membership interest is not a duplicate by default. Keep every observed source and its claims; select a canonical presentation without erasing conflicting prices or status. Postal addresses alone are inadequate for raw land.

Seller descriptions should be labeled source claims until verified. A photo, parcel polygon, utility line nearby, assessor value, or advertised “buildable” label is not a survey, legal access opinion, service commitment, appraisal, or permit.

## Coverage and freshness measures

Use a county-by-land-type dashboard: licensed source coverage; active unique parcels; share with verified parcel identity; source-age distribution; duplicate ratio; price and status conflicts; update latency; stale/withdrawn rate; rights-complete share; usable-media share; verified legal-access share; and sold-comp depth. Compare a sample of county listings with original broker and auction records to estimate missed supply. Label unmeasured coverage unknown.

The expansion loop should discover local sources from original listing brokers and county sale calendars, review the source, resolve its parent and upstream feed, negotiate rights, ingest a sample, measure incremental parcel coverage, and then decide whether ongoing integration earns its operating cost. That repeatable process is the credible path toward “all land,” rather than an unsupported completeness claim.
