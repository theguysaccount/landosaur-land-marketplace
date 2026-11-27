// End-to-end test in headless Chrome against a running copy of the site (local or live).
//   node scripts/e2e.mjs http://localhost:4651
import { launch } from "./cdp.mjs";

const base = (process.argv[2] || "http://localhost:4651").replace(/\/$/, "");
const externalResourceHosts = new Set([
  "tile.openstreetmap.org", "basemap.nationalmap.gov", "hazards.fema.gov",
  "rsio.org", "fonts.googleapis.com", "fonts.gstatic.com",
]);
function isExternalResourceError(error) {
  const url = error.match(/^log: Failed to load resource: .* (https?:\/\/\S+)$/)?.[1];
  if (!url) return false;
  const host = new URL(url).hostname;
  return externalResourceHosts.has(host) || host.endsWith(".tile.openstreetmap.org");
}
const isLocal = /^https?:\/\/(127\.0\.0\.1|localhost)/.test(base);
const { page, close } = await launch();
const results = [];
async function step(name, fn) {
  try { await fn(); results.push(["ok", name]); } catch (e) { results.push(["FAIL", name + ": " + e.message]); }
}
function assert(c, m) { if (!c) throw new Error(m); }
let listing = null;
try {
  await page.viewport(1280, 900, false);
  await step("home split-screen map loads listings and draws markers", async () => {
    await page.goto(base + "/");
    await page.waitFor("/listings match/.test(document.getElementById('map-count').textContent)", 15000);
    assert(await page.eval("document.querySelectorAll('#results li').length > 0"), "no result cards");
    assert(await page.eval("document.querySelectorAll('.leaflet-marker-icon, .marker-cluster, path.leaflet-interactive').length > 0"), "no markers drawn");
  });
  await step("state filter narrows results and links to parcel dossiers", async () => {
    const before = await page.eval("parseInt(document.getElementById('map-count').textContent.replace(/,/g, ''))");
    const code = await page.eval("[...document.querySelector('#filters select[name=state]').options].map(o => o.value).filter(Boolean).pop()");
    await page.eval(`(() => { const s = document.querySelector('#filters select[name=state]'); s.value = '${code}'; s.dispatchEvent(new Event('change', {bubbles: true})); })()`);
    await new Promise((r) => setTimeout(r, 500));
    const after = await page.eval("parseInt(document.getElementById('map-count').textContent.replace(/,/g, ''))");
    assert(after > 0 && after < before, `count ${before} -> ${after}`);
    listing = await page.eval("document.querySelector('#results li a.card-title').getAttribute('href')");
  });
  await step("parcel dossier links to Land Agent ($20), official source, and worksheet adds up", async () => {
    assert(listing, "no listing link");
    await page.goto(new URL(listing, base).href);
    const agentHref = await page.eval("document.querySelector('a.button').href");
    assert(agentHref.includes("/services/"), "primary Land Agent CTA goes to " + agentHref);
    const officialHref = await page.eval("document.querySelector('a[data-official-source=\"1\"]').href");
    assert(/^https:\/\//.test(officialHref) && !officialHref.includes("github.io"), "official source goes to " + officialHref);
    assert(await page.eval("document.body.innerText.includes('Not an offer to sell')"), "notice missing");
    await page.eval("(() => { const f = document.getElementById('worksheet'); f.elements.price.value = '1000'; f.elements.fees.value = '10'; f.elements.survey.value = '500'; f.elements.tax.value = '100'; f.elements.years.value = '2'; f.dispatchEvent(new Event('input')); })()");
    const total = await page.eval("document.querySelector('[data-t=total]').textContent");
    assert(total === "$1,800", "total is " + total);
  });
  await step("program-priced neighborhood lots stay in the application filter", async () => {
    await page.goto(base + "/#state=MI&kind=none&q=neighborhood%20lot");
    await page.waitFor("/listings match/.test(document.getElementById('map-count').textContent)", 15000);
    assert(await page.eval("document.querySelector('#results .badge')?.textContent.includes('Program price')"),
           "Detroit Neighborhood Lots did not appear under Land Bank / Offer");
    await page.eval("document.querySelector('[data-deal-mode=cash]').click()");
    assert(await page.eval("!document.querySelector('#results .card-title')"),
           "a Neighborhood Lot appeared under Buy It Now");
    if (!isLocal) {
      const eligible = await page.eval(`fetch(${JSON.stringify(base)} + "/api/search/?state=MI&mode=offer&q=neighborhood+lot&limit=1")
        .then((r) => r.json()).then((d) => d.results?.[0]?.price_kind === "application" && d.results[0].deal_mode === "offer")`);
      assert(eligible, "search API omitted program-priced land-bank supply");
    }
  });
  await step("50-state land prices observatory renders Georgia chart and counties", async () => {
    await page.goto(base + "/land-prices/georgia/");
    assert(await page.eval("document.querySelectorAll('svg.trend-svg path').length >= 1"), "missing SVG trend chart");
    assert(await page.eval("document.querySelectorAll('table.sortable tbody tr').length >= 100"), "missing Georgia counties");
  });
  await step("interactive Land Analyzer computes all-in cost and power comparison", async () => {
    await page.goto(base + "/analyze/");
    await page.eval("(() => { const f = document.getElementById('form-cost'); f.price.value = '20000'; f.acres.value = '10'; f.closingPct.value = '5'; f.diligence.value = '1000'; f.dispatchEvent(new Event('input')); })()");
    const unlev = await page.eval("document.getElementById('out-unlevered').textContent");
    assert(unlev === "$22,000", "unlevered is " + unlev);
  });
  await step("research guide page renders prose and primary citations", async () => {
    await page.goto(base + "/research/tax-sales/");
    assert(await page.eval("document.querySelector('article.prose') && document.body.innerText.includes('Official')"), "guide missing content");
  });
  await step("universal 50-state Parcel X-Ray and Agent-First /list/ pages load cleanly", async () => {
    await page.goto(base + "/xray/");
    assert(await page.eval("!!document.getElementById('xray-map') && !!document.getElementById('xray-q')"), "missing X-Ray map or search input");
    await page.goto(base + "/list/");
    assert(await page.eval("!!document.getElementById('direct-list-form') && !!document.getElementById('agent-prompt-text')"), "missing /list/ form or AI agent prompt");
    if (!isLocal) {
      const xrayOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/xray/?lat=34.8689&lon=-111.7614").then(r => r.ok ? r.json() : null).then(d => !!(d && d.usgs && d.usgs.elevation_ft > 0 && d.usgs.profile_we && d.usgs.profile_we.length >= 3 && d.roads && d.public_land && d.hazards && d.county && d.county.fips))`);
      assert(xrayOk, "live /api/xray/ failed or returned incomplete 9-agency federal GIS data");
      const listOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/listings/").then(r => r.ok ? r.json() : null).then(d => !!(d && d.storage_configured === true && Array.isArray(d.listings)))`);
      assert(listOk, "live /api/listings/ Blob store check failed");
    }
  });
  await step("Land Agent /services/ and 50-state /land-atlas/ charts load cleanly", async () => {
    await page.goto(base + "/services/?parcel=ks-snco-0973604015014000&price=1510&state=KS");
    assert(await page.eval("!!document.getElementById('concierge-form') && document.getElementById('fee-breakdown-live').innerText.includes('$1,661')"), "missing $1,661 (+10%) turnkey breakdown on /services/");
    await page.goto(base + "/land-atlas/");
    await page.waitFor("document.querySelectorAll('#atlas-cartogram .us-tile').length === 50", 12000);
    assert(await page.eval("document.querySelectorAll('#atlas-compare-chart svg path').length >= 2"), "missing multi-state SVG comparison paths");
    assert(await page.eval("document.querySelectorAll('#county-explorer-body tr').length >= 50"), "missing 3,115-county explorer rows");
    if (!isLocal) {
      const concOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/concierge/").then(r => r.ok ? r.json() : null).then(d => !!(d && d.ok && d.initiation_fee_usd === 20 && d.concierge_fee_pct === 10))`);
      assert(concOk, "live /api/concierge/ metadata check failed");
    }
  });
  await step("Below-Market /deals/, 50-State /tax-sales/ Atlas, and /api/alerts/ load cleanly", async () => {
    await page.goto(base + "/deals/");
    assert(await page.eval("document.querySelectorAll('#below-benchmark tbody tr').length >= 10 && document.body.innerText.includes('Land Agent ($20)')"), "missing below-market deals rows");
    await page.goto(base + "/tax-sales/");
    await page.waitFor("document.querySelectorAll('#tax-cartogram a.us-tile').length === 50", 12000);
    assert(await page.eval("document.querySelectorAll('#tax-tbody tr').length === 50"), "expected 50 rows on /tax-sales/");
    if (!isLocal) {
      const alertOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/alerts/").then(r => r.ok ? r.json() : null).then(d => !!(d && d.ok && d.storage_configured === true))`);
      assert(alertOk, "live /api/alerts/ metadata check failed");
    }
  });
  await step("indexing policy matches SITE_INDEXABLE across core hubs", async () => {
    const indexable = await page.eval(`fetch(${JSON.stringify(base)} + "/data/sources.json").then(r => r.json()).then(d => !!d.site.indexable)`);
    const want = indexable ? "index" : "noindex";
    const paths = ["/", "/deals/", "/tax-sales/", "/services/", "/land-atlas/", "/xray/", "/list/", "/direct/", "/land-for-sale/", "/land-prices/", "/land-prices/georgia/", "/analyze/", "/research/", "/new/", "/closing-soon/"];
    const actual = await page.eval(`Promise.all(${JSON.stringify(paths)}.map(async (path) => {
      const response = await fetch(${JSON.stringify(base)} + path);
      if (!response.ok) throw new Error(path + " HTTP " + response.status);
      const doc = new DOMParser().parseFromString(await response.text(), "text/html");
      return doc.querySelector('meta[name=robots]')?.content || "";
    }))`);
    paths.forEach((path, index) => assert(actual[index].startsWith(want), path + " should be " + want));
  });
  await step("key templates fit a 375px phone screen with zero horizontal overflow", async () => {
    await page.viewport(375, 812, true);
    const bad = [];
    const listingRel = new URL(listing, base).pathname.replace(new URL(base + "/").pathname, "/");
    for (const p of ["/", "/deals/", "/tax-sales/", "/services/", "/land-atlas/", "/xray/", "/list/", "/direct/", "/land-for-sale/", "/land-prices/", "/land-prices/georgia/", "/analyze/", "/research/", "/research/tax-sales/", "/closing-soon/", listingRel]) {
      await page.goto(base + p);
      if (p === "/") await page.waitFor("/listings match/.test(document.getElementById('map-count').textContent)");
      if (p === "/land-atlas/") await page.waitFor("document.querySelector('#county-explorer-body tr')");
      if (p === "/tax-sales/") await page.waitFor("document.querySelector('#tax-tbody tr')");
      const w = await page.eval("document.documentElement.scrollWidth");
      if (w > 375) bad.push(p + " is " + w + "px wide");
    }
    assert(!bad.length, bad.join("; "));
  });
  await step("zero site console errors", async () => {
    const errs = page.errors.filter((error) => !isExternalResourceError(error));
    const external = page.errors.length - errs.length;
    if (external) console.log(`Observed ${external} external map tile or font request errors`);
    assert(!errs.length, errs.slice(0, 5).join(" | "));
  });
} finally {
  await close();
}
for (const [s, n] of results) console.log(s.padEnd(5), n);
if (results.some(([s]) => s !== "ok")) process.exitCode = 1;
