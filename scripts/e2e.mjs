// End-to-end test in headless Chrome against a running copy of the site (local or live).
//   node scripts/e2e.mjs http://localhost:4651
import { launch } from "./cdp.mjs";

const base = (process.argv[2] || "http://localhost:4651").replace(/\/$/, "");
const externalResourceHosts = new Set([
  "tile.openstreetmap.org", "basemap.nationalmap.gov", "hazards.fema.gov",
  "rsio.org", "fonts.googleapis.com", "fonts.gstatic.com",
  "edits.nationalmap.gov", "www.mrlc.gov", "fwsprimary.wim.usgs.gov",
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
    await page.eval(`(() => {
      const select = document.querySelector('#filters select[name=state]');
      select.value = 'KS';
      select.dispatchEvent(new Event('change', {bubbles: true}));
    })()`);
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
  await step("archived parcel keeps its original URL, official attribution and noindex policy", async () => {
    const path = "/land/tx-dal-00000141211000000/";
    const [head, missing] = await Promise.all([
      fetch(base + path, { method: "HEAD", signal: AbortSignal.timeout(10000) }),
      fetch(base + "/land/no-such-parcel-for-release-check/", { method: "HEAD", signal: AbortSignal.timeout(10000) }),
    ]);
    assert(head.status === 200 && head.headers.get("x-robots-tag")?.includes("noindex"), "archive HEAD or noindex failed");
    assert(missing.status === 404, "unknown parcel did not return 404");
    await page.goto(base + path);
    assert(await page.eval(`location.pathname === ${JSON.stringify(path)} &&
      document.querySelector('link[rel=canonical]').href.endsWith(${JSON.stringify(path)}) &&
      document.querySelector('meta[name=robots]').content.startsWith('noindex') &&
      document.querySelector('a[data-official-source="1"]').href.startsWith('https://') &&
      document.body.innerText.includes('It is not an offer')`), "archived parcel content or canonical URL changed");
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
  await step("search API serves the inventory from the same release as the map", async () => {
    const match = await page.eval(`(async () => {
      const { rows } = await fetch("/data/map.json", { cache: "no-cache" }).then((r) => r.json());
      const latest = rows.findLast((row) => row[8] && row[1] === null && (!row[15] || row[15] > Date.now()));
      if (!latest) return false;
      const params = new URLSearchParams({ state: latest[3], q: latest[9], limit: "100" });
      const response = await fetch("/api/search/?" + params);
      if (!response.ok) return false;
      const { results } = await response.json();
      return results.some((row) => row.id === latest[0] && row.lat === null && row.lon === null);
    })()`);
    assert(match, "search omitted an active unlocated listing published on the map");
  });
  await step("source totals distinguish active listings from archived records", async () => {
    await page.goto(base + "/sources/");
    const good = await page.eval(`fetch("/data/sources.json").then((r) => r.json()).then(({ site, sources }) =>
      sources["delaware-in"].archived && sources["delaware-in"].active_count === 0 &&
      Object.values(sources).reduce((sum, s) => sum + s.active_count, 0) === site.current &&
      document.querySelector("main").textContent.includes("archived source"))`);
    assert(good, "source directory counted archived records as current");
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
      const xrayOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/xray/?lat=34.8689&lon=-111.7614").then(r => r.ok ? r.json() : null).then(d => !!(d && d.usgs && d.usgs.elevation_ft > 0 && d.usgs.profile_we && d.usgs.profile_we.length >= 3 && d.roads && d.public_land && d.hazards && d.county && d.county.fips && d.utility?.providers?.some(p => p.residential_usd_per_kwh > 0)))`);
      assert(xrayOk, "live /api/xray/ failed or returned incomplete federal GIS or EIA utility data");
      const listOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/listings/").then(r => r.ok ? r.json() : null).then(d => !!(d && d.storage_configured === true && Array.isArray(d.listings)))`);
      assert(listOk, "live /api/listings/ Blob store check failed");
    }
  });
  await step("Land Agent /services/ and 50-state /land-atlas/ charts load cleanly", async () => {
    await page.goto(base + "/services/?parcel=ks-snco-0973604015014000&price=1&state=AK&lat=60&lon=-150");
    await page.waitFor("document.getElementById('fee-breakdown-live').innerText.includes('$1,661')", 12000);
    assert(await page.eval(`(() => {
      const form = document.getElementById('concierge-form');
      return form.state.value === 'KS' && form.apn.value === '0973604015014000' &&
        Math.abs(Number(form.lat.value) - 39.047502) < 0.00001 &&
        document.getElementById('selected-parcel-banner').innerText.includes('Shawnee County');
    })()`), "parcel details on /services/ differ from the official inventory");
    await page.goto(base + "/land-atlas/");
    await page.waitFor("document.querySelectorAll('#atlas-cartogram .us-tile').length === 50", 12000);
    assert(await page.eval("document.querySelectorAll('#atlas-compare-chart svg path').length >= 2"), "missing multi-state SVG comparison paths");
    assert(await page.eval("document.querySelectorAll('#county-explorer-body tr').length >= 50"), "missing county explorer rows");
    const atlasCountyCoverage = await page.eval(`fetch(${JSON.stringify(base)} + "/data/atlas.json")
      .then(r => r.json()).then(({counties}) => {
        const coverage = document.querySelector("#atlas-county-coverage");
        const reporting = counties.filter(row => row[4] != null).length.toLocaleString("en-US");
        const total = counties.length.toLocaleString("en-US");
        return coverage.querySelector("strong").textContent === reporting &&
          coverage.querySelector("small").textContent.includes(total) &&
          document.querySelector("#county-st-filter option").textContent.includes(total);
      })`);
    assert(atlasCountyCoverage, "county explorer coverage differs from the published data");
    if (!isLocal) {
      const concOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/concierge/").then(r => r.ok ? r.json() : null).then(d => !!(d && d.ok && d.initiation_fee_usd === 20 && d.concierge_fee_pct === 10))`);
      assert(concOk, "live /api/concierge/ metadata check failed");
    }
  });
  await step("off-market letter and five-stage order tracker reflect form and server data", async () => {
    await page.goto(base + "/services/?paid=1&service=unlisted_outreach&county=Van+Buren+County&state=AR&apn=FIELD-APN&acres=2");
    assert(await page.eval(`(() => {
      const form = document.getElementById("concierge-form");
      form.max_budget.value = "4000";
      form.max_budget.dispatchEvent(new Event("input", { bubbles: true }));
      const brief = document.getElementById("acquisition-brief");
      return !brief.hidden && brief.innerText.includes("FIELD-APN") && brief.innerText.includes("$4,000") &&
        !document.getElementById("selected-parcel-banner").innerText.includes("Payment Received");
    })()`), "document or checkout return showed incorrect details");

    // Stub the status response inside the test browser only. No requests or test orders go to Blob.
    await page.eval(`(() => {
      const original = window.fetch;
      window.fetch = function (url, ...options) {
        if (!String(url).includes("/api/concierge/?code=AGT-0000ABCD")) return original(url, ...options);
        return Promise.resolve(Response.json({ order: {
          confirmation_code: "AGT-0000ABCD", parcel_title: "Test order", estimated_base_price: 4000,
          concierge_fee_10pct: 400, estimated_turnkey_total: 4400,
          progress: ["dossier_opened", "initiation_confirmed", "diligence", "outreach", "transfer"].map((id, index) =>
            ({ id, state: ["complete", "complete", "current", "pending", "pending"][index] }))
        } }));
      };
      const tracking = document.getElementById("track-order-form");
      tracking.code.value = "AGT-0000ABCD";
      tracking.requestSubmit();
    })()`);
    await page.waitFor("document.querySelectorAll('.order-progress li').length === 5");
    assert(await page.eval(`document.querySelector(".order-progress [aria-current=step]").textContent.includes("title / lien") &&
      document.getElementById("track-order-out").textContent.includes("$4,400")`), "progress or itemized estimate missing");
  });
  await step("drawn X-Ray boundary measures and carries its coordinates into the Land Agent form", async () => {
    await page.goto(base + "/xray/#lat=35.42&lon=-92.45");
    await page.eval(`(() => {
      document.querySelector("#xray-draw [data-draw-start]").click();
      const map = document.getElementById("xray-map"), rect = map.getBoundingClientRect();
      for (const [x, y] of [[.45,.45],[.54,.46],[.52,.54],[.44,.53]]) {
        map.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: rect.left + rect.width*x, clientY: rect.top + rect.height*y }));
      }
      document.querySelector("#xray-draw [data-draw-finish]").click();
    })()`);
    assert(await page.eval("!document.getElementById('xray-measurements').hidden && document.getElementById('xray-measurements').textContent.includes('sq ft')"),
           "drawing did not produce area and perimeter");
    const links = await page.eval(`(() => {
      const href = document.querySelector('#xray-actions a[href*="/services/"]').href;
      const q = new URL(href).searchParams;
      return [href, q.get("service"), Number(q.get("acres")), q.get("boundary"), location.hash];
    })()`);
    assert(links[1] === "unlisted_outreach" && links[2] > 0 && links[3] && links[4].includes("poly="),
           "boundary or acreage missing from acquisition and share links");
    if (!isLocal) {
      await page.waitFor("document.querySelector('[data-utility-card] li')", 15000);
      const power = await page.eval(`document.querySelector('#xray-actions a[href*="/analyze/"]').href`);
      await page.goto(power);
      assert(await page.eval("!document.getElementById('tab-power').hidden && document.getElementById('form-power').kwhRate.value > 0"),
             "EIA rate did not open and prefill the power comparison");
    }
  });
  await step("Atlas momentum, regions, inflation adjustment and embeds use the published series", async () => {
    await page.goto(base + "/land-atlas/");
    await page.waitFor("document.querySelectorAll('#atlas-scatter circle').length >= 45");
    assert(await page.eval("document.querySelectorAll('.atlas-region-row').length === 4"), "missing Census regions");
    await page.eval(`(() => { const s = document.getElementById("cmp-scale"); s.value = "real"; s.dispatchEvent(new Event("change")); })()`);
    assert(await page.eval("document.getElementById('atlas-inflation-note').innerText.includes('CPI-U')"), "CPI source or period absent");
    await page.eval("document.querySelector('[data-share-chart=momentum]').click()");
    assert(await page.eval("document.querySelector('dialog[open] textarea').value.includes('embed=momentum')"), "no embeddable URL");
    await page.goto(base + "/land-atlas/?embed=momentum");
    await page.waitFor("document.querySelector('#atlas-scatter circle')");
    assert(await page.eval("document.body.classList.contains('chart-embed')"), "embed did not select the chart view");
    await page.goto(base + "/land-prices/georgia/");
    assert(await page.eval(`document.querySelector('a[href="/tax-sales/#state-GA"]') && document.querySelector('#state-price-chart [data-share-chart]')`),
           "state tax-sale or state chart share link missing");
  });
  await step("Below-Market /deals/, 50-State /tax-sales/ Atlas, and /api/alerts/ load cleanly", async () => {
    await page.goto(base + "/deals/");
    assert(await page.eval("document.querySelectorAll('#below-benchmark tbody tr').length >= 10 && document.body.innerText.includes('Land Agent ($20)')"), "missing below-market deals rows");
    await page.goto(base + "/tax-sales/#state-WY");
    await page.waitFor("document.querySelectorAll('#tax-cartogram a.us-tile').length === 50", 12000);
    assert(await page.eval("document.querySelectorAll('#tax-tbody tr').length === 50"), "expected 50 rows on /tax-sales/");
    await page.waitFor(`(() => {
      const row = document.getElementById("state-WY").getBoundingClientRect();
      return row.top >= 0 && row.top < innerHeight;
    })()`);
    const stateFilters = await page.eval(`(() => {
      const state = document.getElementById("state-WY");
      const search = document.getElementById("tax-search");
      document.querySelector('[data-tax-mode=deed]').click();
      search.value = "Hawaii";
      search.dispatchEvent(new Event("input"));
      const filtered = state.hidden && state.getClientRects().length === 0;
      document.querySelector('[data-ts-code=WY] strong').click();
      return [filtered, !state.hidden, search.value, location.hash,
              document.querySelector('[data-tax-mode=all]').getAttribute("aria-pressed"),
              document.getElementById("tax-count").textContent];
    })()`);
    assert(stateFilters[0] && stateFilters[1] && !stateFilters[2] && stateFilters[3] === "#state-WY" &&
           stateFilters[4] === "true" && stateFilters[5] === "Showing 50 of 50 U.S. states",
           "cartogram did not restore the linked row after filtering");
    if (!isLocal) {
      const alertOk = await page.eval(`fetch(${JSON.stringify(base)} + "/api/alerts/").then(r => r.ok ? r.json() : null).then(d => !!(d && d.ok && d.storage_configured === true))`);
      assert(alertOk, "live /api/alerts/ metadata check failed");
    }
  });
  await step("drawn rectangle filters inventory and is included in a saved alert", async () => {
    await page.goto(base + "/");
    await page.waitFor("/listings match/.test(document.querySelector('#map-count')?.textContent)");
    const counts = await page.eval(`(() => {
      const count = () => parseInt(document.getElementById("map-count").textContent.replace(/,/g, ""));
      const before = count(), map = document.getElementById("map"), rect = map.getBoundingClientRect();
      map.querySelector("[data-draw-start]").click();
      const shape = map.querySelector("[data-draw-shape]");
      shape.value = "rectangle";
      shape.dispatchEvent(new Event("change"));
      for (const [x,y] of [[.24,.28],[.72,.78]]) {
        map.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: rect.left + rect.width*x, clientY: rect.top + rect.height*y }));
      }
      document.getElementById("open-alert-modal").click();
      return [before, count(), location.hash, document.getElementById("alert-filter-summary").textContent];
    })()`);
    assert(counts[1] > 0 && counts[1] < counts[0] && counts[2].includes("area=") && counts[3].includes("Drawn search area"),
           "the drawn area did not reach the map filter and saved alert");
  });
  await step("official Hillshade, NLCD, PAD-US, wetlands and flood layers load", async () => {
    const drawn = "-92.465,35.413;-92.442,35.413;-92.442,35.429;-92.465,35.429";
    await page.goto(base + "/?map=layers#area=" + encodeURIComponent(drawn));
    await page.waitFor("/listings match/.test(document.querySelector('#map-count')?.textContent)");
    const layers = [
      ["USGS 3DEP Hillshade", "USGSShadedReliefOnly"], ["NLCD Land Cover", "mrlc_Land-Cover"],
      ["PAD-US Managed Public Lands", "PAD_US_4_1"], ["USFWS Wetlands", "/Wetlands/MapServer/export"],
      ["FEMA Flood Zones", "NFHL"],
    ];
    function selectLayer(label, enabled) {
      return page.eval(`(() => {
        const labels = [...document.querySelectorAll("#map .leaflet-control-layers-list label")];
        const entry = labels.find((node) => node.textContent.trim().startsWith(${JSON.stringify(label)}));
        const input = entry?.querySelector("input");
        if (!input) return false;
        if (input.checked !== ${enabled}) input.click();
        return input.checked === ${enabled};
      })()`);
    }
    for (const [label, urlPart] of layers) {
      const restore = label === "USGS 3DEP Hillshade"
        ? () => selectLayer("Streets", true)
        : () => selectLayer(label, false);
      const loaded = `[...document.querySelectorAll("#map .leaflet-tile")].some((tile) =>
        tile.src.includes(${JSON.stringify(urlPart)}) && tile.complete && tile.naturalWidth > 0)`;
      assert(await selectLayer(label, true), "missing layer " + label);
      try {
        await page.waitFor(loaded, 15000);
      } catch {
        // Reopen a real layer once when its remote service does not return a tile on the first attempt.
        assert(await restore() && await selectLayer(label, true), "could not reopen " + label);
        try {
          await page.waitFor(loaded, 20000);
        } catch {
          throw new Error(label + " returned no visible official tile on either attempt");
        }
      }
      assert(await restore(), "could not restore the map after testing " + label);
    }
  });
  await step("watchlist compares parcels and produces valid CSV, GeoJSON, KML and GPX files", async () => {
    await page.goto(base + "/#state=KS");
    await page.waitFor("document.querySelectorAll('#results .card-title').length >= 2");
    await page.eval(`(() => {
      for (const index of [0, 1]) {
        const card = () => document.querySelectorAll("#results li")[index];
        card().querySelector(".card-acts button:nth-of-type(1)").click();
        card().querySelector(".card-acts button:nth-of-type(2)").click();
      }
      document.querySelector("[data-open-compare]").click();
      window.testExports = {};
      const makeURL = URL.createObjectURL;
      URL.createObjectURL = function (blob) {
        blob.text().then((text) => { testExports[blob.type] = text; });
        return makeURL.call(URL, blob);
      };
      const click = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () { if (!this.download) return click.call(this); };
    })()`);
    assert(await page.eval(`document.querySelector(".compare-acquisition a")?.href.includes("/services/?") &&
      document.querySelectorAll(".compare-acquisition option").length === 2`), "comparison could not select a parcel for acquisition");
    await page.eval(`document.querySelector("[data-close-compare]").click()`);
    for (const [key, mime] of [["CSV","text/csv;charset=utf-8"], ["GeoJSON","application/geo+json"], ["KML","application/vnd.google-earth.kml+xml"], ["GPX","application/gpx+xml"]]) {
      await page.eval(`document.getElementById("watchlist-format").value = ${JSON.stringify(key)};
        document.querySelector("[data-export-saved]").click();`);
      await page.waitFor(`testExports[${JSON.stringify(mime)}] && !document.querySelector("[data-export-saved]").disabled`);
    }
    assert(await page.eval(`(() => {
      const xml = (type) => new DOMParser().parseFromString(testExports[type], "application/xml");
      const json = JSON.parse(testExports["application/geo+json"]);
      const kml = xml("application/vnd.google-earth.kml+xml"), gpx = xml("application/gpx+xml");
      return json.features.length === 2 && !!json.features[0].geometry &&
        testExports["text/csv;charset=utf-8"].trim().split(String.fromCharCode(10)).length === 3 &&
        kml.getElementsByTagName("Placemark").length === 2 &&
        gpx.querySelectorAll("wpt, trk").length === 2;
    })()`), "watchlist file did not parse or omitted a parcel");
    await page.eval("localStorage.removeItem('landosaur_saved'); localStorage.removeItem('landosaur_compare')");
  });
  await step("direct auction separates bid, reservation and seller-provided escrow", async () => {
    const stub = await page.send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
      const realFetch = window.fetch;
      window.fetch = (url, ...options) => {
        if (String(url).includes("/api/listings/?id=dir-test")) return Promise.resolve(Response.json({ listing: {
          id: "dir-test", title: "Local browser fixture", status: "active", sale_mode: "auction", seller_type: "agent",
          price: 3000, buy_now_price: 4000, acres: 2, lat: 35.42, lon: -92.45, state: "AR", county: "Van Buren",
          deadline: "2099-01-01T00:00:00Z", checkout_url: "https://www.escrow.com/"
        } }));
        if (String(url).includes("/api/offers/?listing=dir-test")) return Promise.resolve(Response.json({
          bid_count: 0, recent_bids: [], minimum_next_bid: 3000
        }));
        return realFetch(url, ...options);
      };
    })()` });
    try {
      await page.goto(base + "/direct/?id=dir-test");
      await page.waitFor("document.getElementById('offer-form')");
      assert(await page.eval(`(() => {
        const form = document.getElementById("offer-form"), action = form.elements.action;
        action.value = "buy_now";
        action.dispatchEvent(new Event("change"));
        return form.elements.amount.disabled && document.getElementById("deal-action-box").textContent.includes("0 bids placed") &&
          document.querySelector('a[href*="service=direct_closing"]') && !document.querySelector('a[href="https://www.escrow.com/"]');
      })()`), "the live auction interface did not isolate escrow from an unsubmitted reservation");
    } finally {
      await page.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: stub.identifier });
    }
  });
  await step("budget hubs show official price tiers, 50 states and published agency sources", async () => {
    for (const cap of [5000, 10000]) {
      await page.goto(base + "/land-under-" + cap + "/");
      const found = await page.eval(`(() => {
        const tables = [...document.querySelectorAll("table.listings")];
        const prices = tables.flatMap((t) => [...t.querySelectorAll("td[data-label=Price]")].map((cell) => Number(cell.dataset.v)));
        const attributed = tables.every((t) => !!t.querySelector("a[data-official-source='1']"));
        const faq = [...document.querySelectorAll("script[type='application/ld+json']")].some((x) => JSON.parse(x.textContent)["@type"] === "FAQPage");
        const estimate = document.querySelector('[data-label="With Land Agent"]');
        return [prices.length, Math.max(...prices), attributed, faq, document.querySelectorAll("#budget-states tbody tr").length, Boolean(estimate)];
      })()`);
      assert(found[0] > 0 && found[1] <= cap && found[2] && found[3] && found[4] === 50 &&
        found[5] === (cap === 10000), "budget page shows inconsistent prices, links, or schema");
    }
  });
  await step("acreage bands and all 12 state buying guides match their source links", async () => {
    await page.goto(base + "/acreage-for-sale/");
    assert(await page.eval(`["one-to-five", "five-to-twenty", "twenty-plus"].every((key) =>
      document.querySelector("#" + key + " table a[data-official-source='1']"))`),"acreage groups or sources are missing");
    await page.goto(base + "/research/");
    const count = await page.eval(`new Set([...document.querySelectorAll('#field-guides a[href*="/buying-land-in-"]')].map((link) => link.href)).size`);
    assert(count === 12,"expected twelve state guides");
    await page.goto(base + "/research/buying-land-in-texas/");
    assert(await page.eval(`["/land-for-sale/texas/", "/land-prices/texas/", "/tax-sales/#state-TX", "/services/?state=TX"].every((p) =>
      document.querySelector('article.prose') && document.querySelector('a[href="' + p + '"]')) &&
      !!document.querySelector('article.prose') && [...document.querySelectorAll("main .notes a")].some((a) => a.href.includes("statutes.capitol.texas.gov"))`),
      "missing official source or state guide links");
  });
  await step("indexing policy matches SITE_INDEXABLE across core hubs", async () => {
    const indexable = await page.eval(`fetch(${JSON.stringify(base)} + "/data/sources.json").then(r => r.json()).then(d => !!d.site.indexable)`);
    const want = indexable ? "index" : "noindex";
    const paths = ["/", "/land-under-5000/", "/land-under-10000/", "/acreage-for-sale/", "/research/buying-land-in-texas/", "/deals/", "/tax-sales/", "/services/", "/land-atlas/", "/xray/", "/list/", "/direct/", "/land-for-sale/", "/land-prices/", "/land-prices/georgia/", "/analyze/", "/research/", "/new/", "/closing-soon/"];
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
    for (const p of ["/", "/land-under-5000/", "/land-under-10000/", "/acreage-for-sale/", "/research/buying-land-in-texas/", "/deals/", "/tax-sales/", "/services/", "/land-atlas/", "/xray/", "/list/", "/direct/", "/land-for-sale/", "/land-prices/", "/land-prices/georgia/", "/analyze/", "/research/", "/research/tax-sales/", "/closing-soon/", listingRel]) {
      await page.goto(base + p);
      if (p === "/") await page.waitFor("/listings match/.test(document.getElementById('map-count').textContent)");
      if (p === "/land-atlas/") {
        await page.waitFor("document.querySelector('#county-explorer-body tr')");
        const tableOverflow = await page.eval(`(() => {
          const frame = document.querySelector("#atlas-county-explorer .scroll");
          return frame.scrollWidth > frame.clientWidth;
        })()`);
        if (tableOverflow) bad.push(p + " county values require horizontal scrolling");
      }
      if (p === "/tax-sales/") {
        const taxRulesOverflow = await page.eval(`(() => {
          const frame = document.querySelector(".tax-rules").parentElement;
          return frame.scrollWidth > frame.clientWidth;
        })()`);
        if (taxRulesOverflow) bad.push(p + " rules require horizontal scrolling");
      }
      const w = await page.eval("document.documentElement.scrollWidth");
      if (w > 375) bad.push(p + " is " + w + "px wide");
    }
    await page.goto(base + "/tax-sales/#state-WY");
    await page.waitFor(`(() => {
      const row = document.getElementById("state-WY").getBoundingClientRect();
      const header = document.querySelector("header").getBoundingClientRect();
      const concierge = document.querySelector("#state-WY .chip-link").getBoundingClientRect();
      return row.top >= header.bottom && concierge.right <= innerWidth && concierge.bottom <= innerHeight;
    })()`);
    await page.goto(base + "/land/ks-snco-0973604015014000/");
    assert(await page.eval(`(() => {
      const bar = document.querySelector(".mobile-land-agent"), links = document.querySelector(".dossier-metrics .benchmark-pill");
      return bar && getComputedStyle(bar).position === "fixed" && bar.getBoundingClientRect().right <= 375 && !!links;
    })()`), "mobile acquisition bar or county benchmark pill missing");
    await page.goto(base + "/services/?parcel=ks-snco-0973604015014000#start-land-agent");
    await page.waitFor("document.querySelector('#selected-parcel-banner[aria-busy=false] h3')");
    assert(await page.eval(`new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => {
      const top = document.getElementById('start-land-agent').getBoundingClientRect().top;
      resolve(top >= document.querySelector('header').getBoundingClientRect().bottom && top < innerHeight);
    })))`),
      "sticky navigation obscures the Land Agent form heading");
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
