import { createHmac, timingSafeEqual } from "node:crypto";
import { BlobPreconditionFailedError } from "@vercel/blob";
import { ORDER_CODE, readOrder, writeOrder } from "./concierge.js";

const pending = new Set(["awaiting_initiation_payment", "received_pending_invoice"]);

function response(body, status = 200) {
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store, max-age=0", "CDN-Cache-Control": "no-store" },
  });
}

export function verifySignature(raw, header, secret, now = Date.now()) {
  const fields = (header || "").split(",").map((field) => field.trim().split("="));
  const timestamps = fields.filter(([key]) => key === "t");
  const timestamp = timestamps[0]?.[1];
  if (!secret || timestamps.length !== 1 || !/^\d{1,16}$/.test(timestamp || "") ||
      Math.abs(Math.floor(now / 1000) - Number(timestamp)) > 300) return false;

  const digest = createHmac("sha256", secret).update(timestamp + ".").update(raw).digest();
  return fields.some(([key, signature]) => key === "v1" && /^[0-9a-f]{64}$/i.test(signature || "") &&
    timingSafeEqual(digest, Buffer.from(signature, "hex")));
}

export function createWebhook({
  secret = () => process.env.STRIPE_WEBHOOK_SECRET,
  paymentLinkId = () => process.env.STRIPE_LAND_AGENT_PAYMENT_LINK_ID,
  read = readOrder,
  write = writeOrder,
  now = Date.now,
} = {}) {
  return async function handle(request) {
    const signingSecret = secret();
    if (!signingSecret) return response({ error: "Stripe webhook signing is not configured." }, 503);

    const signature = request.headers.get("stripe-signature");
    if (!signature) return response({ error: "Invalid Stripe signature." }, 400);
    const raw = Buffer.from(await request.arrayBuffer());
    if (!verifySignature(raw, signature, signingSecret, now())) {
      return response({ error: "Invalid Stripe signature." }, 400);
    }

    let event;
    try {
      event = JSON.parse(raw.toString("utf8"));
    } catch {
      return response({ error: "Invalid event JSON." }, 400);
    }

    const session = event?.data?.object;
    const expectedLink = paymentLinkId();
    const code = session?.client_reference_id;
    if (event?.type !== "checkout.session.completed" || event.livemode !== true ||
        session?.mode !== "payment" || session.payment_status !== "paid" ||
        session.amount_total !== 2000 || session.currency !== "usd" ||
        !/^plink_\w+$/.test(session.payment_link || "") || (expectedLink && session.payment_link !== expectedLink) ||
        !ORDER_CODE.test(code || "") || !/^cs_live_\w+$/.test(session.id || "") ||
        !/^pi_\w+$/.test(session.payment_intent || "") ||
        !Number.isInteger(event.created) || event.created < 1 || event.created > Math.floor(now() / 1000) + 300) {
      return response({ received: true, ignored: true });
    }

    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        const stored = await read(code);
        if (!stored) return response({ error: "Land Agent order was not found." }, 404);
        const { order, etag } = stored;
        if (order.confirmation_code !== code || order.initiation_fee_usd !== 20) {
          return response({ error: "Land Agent order does not match the payment." }, 409);
        }
        if (order.stripe_session_id === session.id) return response({ received: true, duplicate: true });
        if (order.stripe_session_id || order.paid_at) {
          // A second real payment requires review; leave the original payment and status intact.
          console.warn("[stripe webhook] additional payment for confirmed order", code, session.id);
          return response({ received: true, review_required: true });
        }
        const paidAt = new Date(event.created * 1000).toISOString();
        const timeline = Array.isArray(order.timeline) ? order.timeline : [];
        try {
          await write({
            ...order,
            status: pending.has(order.status) ? "paid_active_diligence" : order.status,
            paid_at: paidAt,
            stripe_session_id: session.id,
            stripe_payment_intent: session.payment_intent,
            amount_paid_cents: session.amount_total,
            timeline: [...timeline, { step: "initiation_confirmed", at: paidAt }],
          }, etag);
          return response({ received: true });
        } catch (error) {
          if (!(error instanceof BlobPreconditionFailedError)) throw error;
        }
      }
    } catch (error) {
      console.error("[stripe webhook] order update failed", error?.name);
    }
    return response({ error: "Unable to update the order. Retry later." }, 503);
  };
}

export const POST = createWebhook();
