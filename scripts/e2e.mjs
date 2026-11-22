// End-to-end test in headless Chrome against a running copy of the site (local or live).
//   node scripts/e2e.mjs http://localhost:4651/landosaur-land-marketplace
import { launch } from "./cdp.mjs";

const base = (process.argv[2] || "http://localhost:4651/landosaur-land-marketplace").replace(/\/$/, "");
const TILE_HOSTS = /tile\.openstreetmap\.org|basemap\.nationalmap\.gov/;
const { page, close } = await launch();
const results = [];
async function step(name, fn) {
  try { await fn(); results.push(["ok", name]); } catch (e) { results.push(["FAIL", name + ": " + e.message]); }
}
function assert(c, m) { if (!c) throw new Error(m); }
let listing = null;
try {
  await page.viewport(1280, 900, false);
  await step("home map loads listings and lists results", async () => {
    await page.goto(base + "/");
    await page.waitFor("/listings match/.test(document.getElementById('map-count').textContent)", 15000);
    assert(await page.eval("document.querySelectorAll('#results li').length > 0"), "no result cards");
    assert(await page.eval("document.querySelectorAll('.leaflet-marker-icon, .marker-cluster, path.leaflet-interactive').length > 0"), "no markers drawn");
  });
  await step("state filter narrows the results", async () => {
    const before = await page.eval("parseInt(document.getElementById('map-count').textContent.replace(/,/g, ''))");
    const code = await page.eval("[...document.querySelector('#filters select[name=state]').options].map(o => o.value).filter(Boolean).pop()");
    await page.eval(`(() => { const s = document.querySelector('#filters select[name=state]'); s.value = '${code}'; s.dispatchEvent(new Event('change', {bubbles: true})); })()`);
    await new Promise((r) => setTimeout(r, 500));
    const after = await page.eval("parseInt(document.getElementById('map-count').textContent.replace(/,/g, ''))");
    assert(after > 0 && after < before, `count ${before} -> ${after}`);
    listing = await page.eval("document.querySelector('#results li a').getAttribute('href')");
  });
  await step("a listing page links to the official source and draws its map", async () => {
    assert(listing, "no listing link");
    await page.goto(new URL(listing, base).href);
    const href = await page.eval("document.querySelector('a.button').href");
    assert(/^https:\/\//.test(href) && !href.includes("github.io"), "button goes to " + href);
    assert(await page.eval("document.body.innerText.includes('Not an offer to sell')"), "notice missing");
  });
  await step("the cost worksheet adds up", async () => {
    await page.goto(base + "/land/" + (await page.eval("location.pathname.split('/').filter(Boolean).pop()")) + "/");
    await page.eval("(() => { const f = document.getElementById('worksheet'); f.elements.price.value = '1000'; f.elements.fees.value = '10'; f.elements.survey.value = '500'; f.elements.tax.value = '100'; f.elements.years.value = '2'; f.dispatchEvent(new Event('input')); })()");
    const total = await page.eval("document.querySelector('[data-t=total]').textContent");
    assert(total === "$1,800", "total is " + total);
  });
  await step("new and closing-soon pages are indexable, listing pages are not", async () => {
    await page.goto(base + "/new/");
    assert((await page.eval("document.querySelector('meta[name=robots]').content")).startsWith("index"), "/new/ not indexable");
    await page.goto(base + "/closing-soon/");
    assert((await page.eval("document.querySelector('meta[name=robots]').content")).startsWith("index"), "/closing-soon/ not indexable");
    await page.goto(new URL(listing, base).href);
    assert((await page.eval("document.querySelector('meta[name=robots]').content")).startsWith("noindex"), "listing page indexable");
  });
  await step("pages fit a 375px phone screen", async () => {
    await page.viewport(375, 812, true);
    const bad = [];
    for (const p of ["/", "/new/", "/closing-soon/", "/sources/", new URL(listing, base).pathname.replace(new URL(base + "/").pathname, "/")]) {
      await page.goto(base + p);
      const w = await page.eval("document.documentElement.scrollWidth");
      if (w > 376) bad.push(p + " is " + w + "px wide");
    }
    assert(!bad.length, bad.join("; "));
  });
  await step("no console errors (map tile hosts excluded)", async () => {
    const errs = page.errors.filter((e) => !TILE_HOSTS.test(e));
    assert(!errs.length, errs.slice(0, 5).join(" | "));
  });
} finally {
  await close();
}
for (const [s, n] of results) console.log(s.padEnd(5), n);
if (results.some(([s]) => s !== "ok")) process.exitCode = 1;
