# OPERATIONS

Everything that runs, how it fails safely, what to watch, and the keys a human can turn later.

- **Production:** https://landosaur.com, Vercel project `persist-always/landosaur-com-staging`.
- **Repository:** `main` tracks `origin/main`. The separately linked Vercel mirror is the source for CLI deployments.

## Local releases

Use `./scripts/publish.sh --no-deploy` to run source syntax checks, API imports, Python tests, a static build,
the output guard, and headless browser E2E. The local browser uses the API handlers with Blob credentials
unset. To refresh inventory, run `./scripts/publish.sh --refresh --no-deploy` or use `--refresh-only` with
agency IDs. Review and commit the snapshot before releasing.

Run `./scripts/publish.sh` from a clean `main` to push, sync the Vercel mirror, and deploy. The script
diffs indexable pages against the pre-release manifest, then runs live browser and read-only API checks before
submitting changed URLs to IndexNow. Set `LANDO_SCREEN_DIR` to save desktop and mobile screenshots in both
themes. Release and crawl workflows in GitHub are manual only and are not used for production releases.

Production indexes the public hubs and active priced or deadline-bearing listing pages. A build with
`SITE_INDEXABLE=false` carries noindex and publishes no sitemap. A failed refresh retains the last successful
snapshot and records the failure in `data/sources.json`. A partial read cannot withdraw listings.

## What to watch

| Signal | Where | Healthy |
|---|---|---|
| Inventory refresh | Local release output and source timestamps | All configured sources return a current snapshot |
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
6. About 30 minutes later, if `SITE_INDEXABLE` is `true`, send the indexed pages to IndexNow once. IndexNow refuses a
   new host for roughly its first 20 minutes, and later deploys send only pages that changed:
   `printf '%s\n' https://land.example.com/new/ https://land.example.com/closing-soon/ > urls.txt && python3 scripts/indexnow.py submit urls.txt https://land.example.com`

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
- **Build scale:** Vercel documents a 15,000-file limit on CLI source uploads and no separate ceiling on static files generated during the build. The release excludes local `dist/` from the upload. Track build and post-build duration as the catalogue grows. [Vercel file limits](https://vercel.com/docs/limits#files)
