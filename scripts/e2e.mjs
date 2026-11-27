// End-to-end test in headless Chrome against a running copy of the site (local or live).
//   node scripts/e2e.mjs http://localhost:4651
import { launch } from "./cdp.mjs";

const base = (process.argv[2] || "http://localhost:4651").replace(/\/$/, "");
const TILE_HOSTS = /tile\.openstreetmap\.org|basemap\.nationalmap\.gov|hazards\.fema\.gov|rsio\.org|fonts\.googleapis\.com|fonts\.gstatic\.com|\/api\/xray/;
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
  await step("parcel dossier links to official source and worksheet adds up", async () => {
    assert(listing, "no listing link");
    await page.goto(new URL(listing, base).href);
    const href = await page.eval("document.querySelector('a.button').href");
    assert(/^https:\/\//.test(href) && !href.includes("github.io"), "button goes to " + href);
    assert(await page.eval("document.body.innerText.includes('Not an offer to sell')"), "notice missing");
    await page.eval("(() => { const f = document.getElementById('worksheet'); f.elements.price.value = '1000'; f.elements.fees.value = '10'; f.elements.survey.value = '500'; f.elements.tax.value = '100'; f.elements.years.value = '2'; f.dispatchEvent(new Event('input')); })()");
    const total = await page.eval("document.querySelector('[data-t=total]').textContent");
    assert(total === "$1,800", "total is " + total);
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
  await step("universal 50-state Parcel X-Ray page loads map and search console", async () => {
    await page.goto(base + "/xray/");
    assert(await page.eval("!!document.getElementById('xray-map') && !!document.getElementById('xray-q')"), "missing X-Ray map or search input");
    if (!isLocal) {
      const xrayOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/xray?lat=35.42&lon=-92.45").then(r => r.ok ? r.json() : null).then(d => !!(d && d.usgs && d.usgs.elevation_ft > 0 && d.county && d.county.fips))`);
      assert(xrayOk, "live /api/xray failed or returned incomplete federal GIS data");
    }
  });
  await step("indexing policy matches SITE_INDEXABLE across core hubs", async () => {
    const indexable = await page.eval(`fetch(${JSON.stringify(base)} + "/data/sources.json").then(r => r.json()).then(d => !!d.site.indexable)`);
    const want = indexable ? "index" : "noindex";
    for (const p of ["/", "/xray/", "/land-for-sale/", "/land-prices/", "/land-prices/georgia/", "/analyze/", "/research/", "/new/", "/closing-soon/"]) {
      await page.goto(base + p);
      assert((await page.eval("document.querySelector('meta[name=robots]').content")).startsWith(want), p + " should be " + want);
    }
  });
  await step("key templates fit a 375px phone screen with zero horizontal overflow", async () => {
    await page.viewport(375, 812, true);
    const bad = [];
    const listingRel = new URL(listing, base).pathname.replace(new URL(base + "/").pathname, "/");
    for (const p of ["/", "/xray/", "/land-for-sale/", "/land-prices/", "/land-prices/georgia/", "/analyze/", "/research/", "/research/tax-sales/", "/closing-soon/", listingRel]) {
      await page.goto(base + p);
      const w = await page.eval("document.documentElement.scrollWidth");
      if (w > 376) bad.push(p + " is " + w + "px wide");
    }
    assert(!bad.length, bad.join("; "));
  });
  await step("no console errors (external tile/telemetry hosts excluded)", async () => {
    const errs = page.errors.filter((e) => !TILE_HOSTS.test(e));
    assert(!errs.length, errs.slice(0, 5).join(" | "));
  });
} finally {
  await close();
}
for (const [s, n] of results) console.log(s.padEnd(5), n);
if (results.some(([s]) => s !== "ok")) process.exitCode = 1;
