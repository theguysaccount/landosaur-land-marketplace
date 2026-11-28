import assert from "node:assert/strict";
import test from "node:test";
import { openOrder } from "../api/concierge.js";

const requestFor = (body) => new Request("http://localhost/api/concierge/", {
  method: "POST",
  body: JSON.stringify({ buyer_name: "Test Buyer", buyer_email: "buyer@example.com", ...body }),
});

test("listed orders price the parcel and run X-Ray from the release inventory", async () => {
  let recorded;
  const response = await openOrder(requestFor({
    parcel_id: "KS-SNCO-0973604015014000", official_price: 1, county: "Wrong County",
    state: "AK", lat: 60, lon: -150, acres: 100, apn: "INCORRECT",
  }), {
    configured: true,
    lookup: async (id) => {
      assert.equal(id, "ks-snco-0973604015014000");
      return { price: 1510, price_kind: "cash", lat: 39.047502, lon: -95.692801,
        county: "Shawnee County", state: "KS", acres: 0.0842, apn: "0973604015014000" };
    },
    xrayAt: async (lat, lon) => {
      assert.deepEqual([lat, lon], [39.0475, -95.6928]);
      return { usgs: { elevation_ft: 939 }, fema: { zone: "X" }, nwi: { within_100m: false },
        roads: { nearest_road_ft: 48 }, county: { benchmark_usd_per_acre: 3700 } };
    },
    write: async (order) => { recorded = order; },
  });
  assert.equal(response.status, 201);
  assert.equal(recorded.apn, "0973604015014000");
  assert.equal(recorded.county, "Shawnee County");
  assert.equal(recorded.state, "KS");
  assert.equal(recorded.acres, 0.0842);
  assert.equal(recorded.xray_summary.elevation_ft, 939);
  assert.equal(recorded.xray_summary.fema_zone, "X");
  assert.equal(recorded.xray_summary.wetlands_100m, false);
  assert.equal(recorded.xray_summary.nearest_road_ft, 48);
  assert.equal(recorded.xray_summary.county_benchmark_per_acre, 3700);
  const receipt = await response.json();
  assert.equal(receipt.official_price, 1510);
  assert.equal(receipt.concierge_fee_10pct, 151);
  assert.equal(receipt.estimated_turnkey_total, 1661);
});

test("unknown parcel IDs create no order", async () => {
  const response = await openOrder(requestFor({ parcel_id: "unavailable" }), {
    configured: true,
    lookup: async () => null,
    write: () => assert.fail("an unavailable parcel must never open an order"),
  });
  assert.equal(response.status, 404);
});

test("seller prices, zero-dollar agency programs, and off-market budgets keep their meaning", async () => {
  const save = { configured: true, write: async () => {} };
  async function receipt(body, parcel) {
    const response = await openOrder(requestFor(body), { ...save, lookup: async () => parcel });
    assert.equal(response.status, 201);
    return response.json();
  }

  const direct = await receipt({ parcel_id: "dir-example", official_price: 100 },
    { price: 4000, price_kind: "min_bid", is_direct: true });
  assert.equal(direct.official_price, null);
  assert.equal(direct.seller_price, 4000);
  assert.equal(direct.price_kind, "min_bid");
  assert.equal(direct.estimated_turnkey_total, 4400);

  const program = await receipt({ parcel_id: "agency-program", max_budget: 900 },
    { price: 0, price_kind: "application", is_direct: false });
  assert.equal(program.official_price, 0);
  assert.equal(program.estimated_turnkey_total, 0);

  const unlisted = await receipt({ apn: "42", service_type: "unlisted_outreach", official_price: 900 });
  assert.equal(unlisted.official_price, null);
  assert.equal(unlisted.estimated_base_price, 900);
  assert.equal(unlisted.estimated_turnkey_total, 990);
});
