import assert from "node:assert/strict";
import { test } from "node:test";
import { runXray } from "../api/xray.js";

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
