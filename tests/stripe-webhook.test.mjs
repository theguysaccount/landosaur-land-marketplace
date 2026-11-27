import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";
import { BlobPreconditionFailedError } from "@vercel/blob";
import { createWebhook } from "../api/stripe-webhook.js";

const secret = "local-test-signing-key";
const now = 1700000000000;
const session = {
  client_reference_id: "AGT-0000ABCD", id: "cs_live_fixture", payment_intent: "pi_fixture",
  payment_link: "plink_fixture", mode: "payment", payment_status: "paid", currency: "usd", amount_total: 2000,
};
const event = { type: "checkout.session.completed", livemode: true, created: now / 1000, data: { object: session } };
const signed = (input = event, t = now / 1000, key = secret) => {
  const body = JSON.stringify(input);
  const v1 = createHmac("sha256", key).update(t + "." + body).digest("hex");
  return new Request("http://localhost/api/stripe-webhook/", {
    method: "POST", body, headers: { "Stripe-Signature": "t=" + t + ",v1=bad,v1=" + v1 },
  });
};
const handler = (extra = {}) => createWebhook({ secret: () => secret, now: () => now, ...extra });

test("missing signing secret returns 503 before reading the body", async () => {
  const r = await handler({ secret: () => "" })(signed());
  assert.equal(r.status, 503);
});
test("invalid and stale signatures return 400", async () => {
  assert.equal((await handler()(signed(event, now / 1000, "wrong-key"))).status, 400);
  assert.equal((await handler()(signed(event, now / 1000 - 301))).status, 400);
});
test("signed but unpaid, unrelated or non-live events do not read orders", async () => {
  const handle = handler({ read: () => assert.fail("Expected no lookup") });
  for (const ignored of [
    { ...event, livemode: false },
    { ...event, type: "other" },
    { ...event, data: { object: { ...session, payment_status: "unpaid" } } },
    { ...event, data: { object: { ...session, amount_total: 1900 } } },
  ]) {
    assert.deepEqual(await (await handle(signed(ignored))).json(), { received: true, ignored: true });
  }
});
test("verified payment advances only once, retrying a concurrent write", async () => {
  let order = {
    confirmation_code: session.client_reference_id, initiation_fee_usd: 20,
    status: "awaiting_initiation_payment", timeline: [{ step: "dossier_opened", at: "2023-11-14T00:00:00.000Z" }],
  };
  let writes = 0;
  const handle = handler({
    read: async (code) => {
      assert.equal(code, session.client_reference_id);
      return { order, etag: "current" };
    },
    write: async (updated, etag) => {
      assert.equal(etag, "current");
      if (++writes === 1) throw new BlobPreconditionFailedError();
      order = updated;
    },
  });
  assert.equal((await handle(signed())).status, 200);
  assert.equal(order.status, "paid_active_diligence");
  assert.equal(order.stripe_payment_intent, session.payment_intent);
  assert.equal(order.amount_paid_cents, 2000);
  assert.deepEqual(order.timeline.at(-1), { step: "initiation_confirmed", at: new Date(now).toISOString() });
  assert.deepEqual(await (await handle(signed())).json(), { received: true, duplicate: true });
  assert.equal(writes, 2);
});
test("verified payment preserves an advanced status and its recorded milestones", async () => {
  const timeline = [{ step: "outreach", at: new Date(now).toISOString() }];
  const r = await handler({
    read: async () => ({
      order: { confirmation_code: session.client_reference_id, initiation_fee_usd: 20, status: "outreach_active", timeline },
      etag: "current",
    }),
    write: async (order) => {
      assert.equal(order.status, "outreach_active");
      assert.deepEqual(order.timeline[0], timeline[0]);
    },
  })(signed());
  assert.equal(r.status, 200);
});
