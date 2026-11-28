import assert from "node:assert/strict";
import test from "node:test";
import "../site/availability.js";

const { closeExpired } = globalThis.LandosaurAvailability;

test("availability closes at the exact cutoff and leaves the cached source row intact", () => {
  const row = ["parcel", null, null, "SC", 500, "min_bid", 1, "auction_terms", 1];
  row[15] = Date.UTC(2026, 11, 1, 14);
  assert.equal(closeExpired(row, row[15] - 1), row);
  const closed = closeExpired(row, row[15]);
  assert.deepEqual(closed.slice(7, 9), ["auction_closed", 0]);
  assert.deepEqual(row.slice(7, 9), ["auction_terms", 1]);
  assert.equal(closeExpired(row.slice(0, 15), row[15]).at(8), 1);
});
