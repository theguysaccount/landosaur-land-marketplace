# OPERATIONS

Everything that runs, how it fails safely, what to watch, and the keys a human can turn later.

- **Live (static edition):** https://theguysaccount.github.io/landosaur-land-marketplace/
- **Original application:** https://landosaur.fly.dev (private repo `theguysaccount/landosaur`). It stays up and
  is never touched from here. This edition is built on top of it, not as a replacement.

## Indexing policy (no cutover)

This repo follows the fleet convention recorded in `~/code/DOMAIN_ROLLOUT.md`:

- Pages that duplicate what the original serves (map, listing, state and county pages, sources, about, data) are
  always `noindex, follow`, never in the sitemap and never sent to IndexNow. There is no switch that indexes them:
  the original is never replaced.
- Repository variable **`SITE_INDEXABLE`**: unset means the whole copy is staged (every page noindex, robots.txt
  `Disallow: /`, no sitemap, no IndexNow). `true` indexes only the pages the original does not have, `/new/` and
  `/closing-soon/`, which go into the sitemap and to IndexNow. Set to `true` on 2026-11-22, as the parent session
  instructed ("index pages that add something new").
- The weekly check fails if the live site is inconsistent (a duplicate page without noindex, or `/new/` and
  robots.txt disagreeing with the live build's `SITE_INDEXABLE`).

## Automated jobs

| Workflow | When | What it does | How it fails safely |
|---|---|---|---|
| `crawl.yml` Crawl and deploy | Daily 09:37 UTC; by hand | Reads each official source (`lando/adapters.py`): St. Louis open-data exports + city GIS outlines, Arkansas Commissioner of State Lands auction feed + state GIS outlines, Wisconsin BCPL page, Alaska Mental Health Trust catalogue + its GIS, Alaska DNR land-sales page. Identifies itself (`landosaur-land-marketplace/1.0 (+repo URL)`), obeys robots.txt, waits a second between requests to a host. Merges into `data/` (new listings get today's date; a listing leaves only after two complete reads without it), refreshes the cached county land values from the US County Land Index, tests, builds, guards, commits, then calls `deploy.yml`. | A failing source is retried, then keeps its last good listings (recorded in `data/sources.json`: `ok: false`, message, failure count) and the run continues. A partial or much smaller read never removes listings. A failed test or guard stops before commit and deploy. |
| `deploy.yml` Build and deploy | Called by the crawl; code pushes; by hand | Unit tests, build (about 10,400 pages), guard (`scripts/check_dist.py`: titles, canonicals, one h1, not-an-offer notice, indexing policy, sitemap = indexable pages, every listing has a page with an official https link, no owner fields), share images (headless Chrome), browser test of the built site, Pages deploy with a second attempt, browser test of the live site, IndexNow for changed indexable pages. | Anything failing before deploy leaves the last good site live. |
| `checks.yml` Weekly checks | Tuesdays 06:11 UTC; by hand | `scripts/health.py`: key pages and files answer; every source read successfully within 7 days and not failing 3 times in a row; indexing policy matches; 20 sampled listings answer with an official link; dispatches the crawl when the newest read is over 48 hours old. `scripts/linkcheck.py`: sampled listing pages and every source's catalogue page. Browser test on the live site. | Read-only apart from dispatching the crawl. Source pages that fail only warn. Failures email the repository owner. |
| `keepalive.yml` | Called by scheduled workflows | Re-enables workflows disabled for inactivity; heartbeat commit after 40 quiet days. | Harmless when nothing is needed. |
| `ci.yml` | Every push and pull request | Unit tests (Python 3.10 and 3.13), full build plus guard, script syntax. | Read-only. |

GitHub fires schedules late on this account. Nothing depends on exact timing; the weekly check re-dispatches a
stalled crawl. `checks.yml` carries a temporary line `47 * 22,23 11 *` that only fired on 22 and 23 November 2026 to
prove the schedule trigger; delete it when convenient (it would fire again on those dates next year).

## What to watch

| Signal | Where | Healthy |
|---|---|---|
| Daily crawl | Actions tab; failure emails | Green; a "Crawl YYYY-MM-DD" commit most days |
| Source health | `/sources/` page or `data/sources.json` (`ok`, `failures`, `last_success`, `notes`) | All `ok`, read within a day |
| Inventory | `/data/sources.json` `site.current`, `/new/`, `/closing-soon/` | Counts move with the agencies |
| Original app | https://landosaur.fly.dev/api/health | Up. On 2026-11-22 it did not answer (timeouts on every path, also by IP). That is outside this repo; Jack's Fly account owns it |

## Changing the address (custom domain), DNS by the domain-rollout session

The base URL is one setting: the repository variable **`SITE_URL`** (fleet convention; `LANDO_BASE_URL` also works).
Default: `https://theguysaccount.github.io/landosaur-land-marketplace`. Canonicals, feeds, share cards, the
sitemap and IndexNow all follow it. To move the site to, for example, `land.example.com`:

1. DNS (domain-rollout session or Jack): `CNAME land -> theguysaccount.github.io.`
2. `~/.local/bin/gh api -X PUT repos/theguysaccount/landosaur-land-marketplace/pages -f cname=land.example.com`
3. `~/.local/bin/gh variable set SITE_URL -R theguysaccount/landosaur-land-marketplace -b https://land.example.com`
4. `~/.local/bin/gh workflow run deploy.yml -R theguysaccount/landosaur-land-marketplace`
5. Once GitHub has issued the certificate: `~/.local/bin/gh api -X PUT repos/theguysaccount/landosaur-land-marketplace/pages -F https_enforced=true`

The original stays where it is; nothing in this procedure touches landosaur.fly.dev. Moving the address and
indexing are separate switches (`SITE_URL`, `SITE_INDEXABLE`).

## Keys Jack can turn later

| Key | Why | Exact steps |
|---|---|---|
| **Custom domain** | Its own address (no Landosaur domain was in the 2026-08-30 portfolio) | Steps above. Candidates to check before buying anything: landosaur.com / landosaur.land (new registrations); a subdomain of an owned domain needs no purchase. |
| **Money: parcel report** | The evaluator's cheapest test: a paid parcel-diligence report sold from listing pages | Pages is non-commercial, so the checkout lives elsewhere (for example a Stripe Payment Link or a page on another host). Create it, then `gh variable set LANDO_REPORT_URL -b <url>` and redeploy. Every listing page then shows "Order a parcel report" linking to `<url>?listing=<id>`. Fulfilment needs a person or a separate service; nothing here takes payment. |
| **Money: support link** | Donations without commerce on Pages | Set up GitHub Sponsors (needs Jack's identity and bank details), then `gh variable set LANDO_SUPPORT_URL -b https://github.com/sponsors/theguysaccount` and redeploy. |
| **Analytics** | Measure the activation event (opening an official listing link from a listing page) | Create a GoatCounter site; `gh variable set LANDO_GOATCOUNTER -b https://<code>.goatcounter.com/count`; redeploy. Cookieless. |
| **Stage the copy again** | If Jack wants this edition out of search entirely | `gh variable delete SITE_INDEXABLE -R theguysaccount/landosaur-land-marketplace`; run `deploy.yml`. |
| **More sources** | Coverage beyond MO, AR, WI and AK | Add an adapter to `lando/adapters.py` with a parser test. Candidates and why they are not in yet are on `/sources/`. GSA RealEstateSales.gov disallows crawlers in robots.txt: stays out. |

## Scheduled Claude routine (optional)

No AI-written content is needed: every page is built from agency facts. For a monthly source review:

> In ~/code/landosaur-land-marketplace (git pull): read data/sources.json and the last 7 crawl runs. For any source
> that failed or whose count moved sharply, open the agency page in a browser and fix the adapter in
> lando/adapters.py with a parser test. Look for one new official land source (county tax-sale lists, state land
> offices) whose robots.txt allows crawling and whose terms allow linking, and add it the same way. Run the tests,
> commit, push. Do not post anywhere.

## Failure playbook

- **A source "kept on last good data":** the message is in `/sources/`. Timeouts usually clear next day. A
  `StructureError` means the agency changed its page: compare with the parser and its test, fix, push.
- **Many listings marked missing:** reads that are partial or under half the previous size never withdraw anything;
  check the agency's inventory before changing the rule.
- **Pages size:** about 175 MB of the 1 GB limit, mostly St. Louis lots.
