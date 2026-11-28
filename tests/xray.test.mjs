import assert from "node:assert/strict";
import { test } from "node:test";
import { GET, runXray } from "../api/xray.js";

test("county utility lookup uses published EIA rates and needs no live GIS requests", async (t) => {
  const fetchSpy = t.mock.method(globalThis, "fetch", () => { throw new Error("unexpected upstream request"); });
  const endpoint = "https://landosaur.com/api/xray/?layer=utility&county_fips=";
  const response = await GET(new Request(endpoint + "05045"));
  assert.equal(response.status, 200);
  const { utility } = await response.json();
  assert.equal(utility.county_fips, "05045");
  assert.equal(utility.state_code, "AR");
  assert.ok(utility.year >= 2025);
  assert.ok(utility.state_average_usd_per_kwh > 0);
  assert.match(utility.state_average_source, /epa_02_10\.html$/);
  const conway = utility.providers.find((provider) => provider.id === 4280);
  assert.ok(conway?.residential_usd_per_kwh > 0);
  if (utility.year === 2025) {
    assert.equal(utility.state_average_usd_per_kwh, 0.1287);
    assert.equal(conway.residential_usd_per_kwh, 0.09494);
  }
  assert.match(utility.state_commission_url, /viewCommissionRoster\?id=76400000057$/);
  assert.equal((await GET(new Request(endpoint + "5045"))).status, 400);
  assert.equal((await GET(new Request(endpoint + "99999"))).status, 404);
  assert.equal(fetchSpy.mock.callCount(), 0);
});

test("wetland screening distinguishes an empty survey result from an upstream error", async (t) => {
  let wetlands = { error: { code: 500, message: "Unavailable" } };
  t.mock.method(globalThis, "fetch", async (input) => {
    if (new URL(input).hostname === "fwspublicservices.wim.usgs.gov") {
      return Response.json(wetlands);
    }
    return new Response(null, { status: 503 });
  });

  const missing = await runXray(35.42, -92.45);
  assert.equal(missing.nwi.status, "unavailable");
  assert.equal(missing.nwi.within_100m, undefined);

  wetlands = { features: [] };
  const empty = await runXray(35.42, -92.45);
  assert.equal(empty.nwi.status, "ok");
  assert.equal(empty.nwi.within_100m, false);

  wetlands = { features: [], exceededTransferLimit: true };
  const truncated = await runXray(35.42, -92.45);
  assert.equal(truncated.nwi.status, "unavailable");
});
