# Landosaur: static edition

Government and auction land for sale, on one map, with every listing linked to its official source.

**Live:** https://theguysaccount.github.io/landosaur-land-marketplace/

A daily GitHub Actions crawl reads official inventories (St. Louis city vacant lots, Arkansas Commissioner of State
Lands tax-sale parcels, Wisconsin Board of Commissioners of Public Lands, Alaska Mental Health Trust Land Office,
Alaska DNR land sales), keeps parcel outlines from the agencies' own GIS, and publishes:

- a map with filters (state, fixed price or auction, price, acreage, search) and a result list;
- one page per listing: status, price or minimum bid, acreage, location, the agency's facts with the date they were
  read and a link to each, the parcel outline, county land values from the
  [US County Land Index](https://theguysaccount.github.io/land-index-fund/), and an all-in cost worksheet;
- state and county pages, **new listings** and **closing soon** pages with Atom feeds, CSV/JSON downloads.

Not an offer to sell; Landosaur does not sell or broker land. No legal, tax or investment advice.

This edition is built on top of the original Landosaur application (https://landosaur.fly.dev), which stays live.
Pages that duplicate the original carry `noindex`; see [OPERATIONS.md](OPERATIONS.md).

## Run

Python 3.9+ (standard library only). Node 22+ and Chrome only for the browser test and share images.

```bash
python3 -m lando.refresh --land-index   # crawl every source politely (about 3 minutes)
python3 -m lando.build dist             # build the site
python3 scripts/check_dist.py dist      # the guard that runs before every deploy
```

Serve `dist/` under its base path:

```bash
mkdir -p /tmp/lando-root && ln -sfn "$PWD/dist" /tmp/lando-root/landosaur-land-marketplace && python3 -m http.server 4652 --directory /tmp/lando-root
```

## Test

```bash
python3 -m unittest discover -s tests -t .
node scripts/e2e.mjs http://localhost:4652/landosaur-land-marketplace
```

## Deploy

Pushes to `main` deploy through `.github/workflows/deploy.yml`; the daily crawl commits data and deploys. Jobs,
failure handling and the keys for a domain, money and analytics are in [OPERATIONS.md](OPERATIONS.md).

## What is in this repository

Only what the static site needs: the crawlers and builder (`lando/`), client scripts and styles (`site/`, with
Leaflet and Leaflet.markercluster vendored under their licences), the public listing data (`data/`), tests and
scripts. The original application's server code, admin tools, database, private documents and credentials are not
here and never were.

## Licence

Code: MIT. Listing facts belong to the agencies that publish them. Map tiles: OpenStreetMap contributors and USGS
The National Map.
