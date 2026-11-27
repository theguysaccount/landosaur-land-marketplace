/**
 * Landosaur Live Bidding & Buy-It-Now Checkout / Reservation API (Vercel Fluid Compute + Vercel Blob).
 *
 * Powers real buyer actions on Direct Seller/Agent listings:
 *   - GET  /api/offers/?listing=<id> -> Current bid count, high bid, min next bid, anonymized bid tape (starts honestly at 0!)
 *   - POST /api/offers/              -> Place a live Auction Bid, Buy-It-Now Reservation, or Written Offer
 */
import crypto from "node:crypto";
import { BlobError, BlobPreconditionFailedError } from "@vercel/blob";
import { checkoutUrl, LISTING_PREFIX, OFFER_PREFIX, readDirect, writeDirect } from "../lib/direct-store.js";

function jsonResp(body, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, max-age=0", "CDN-Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}

function cleanStr(v, max = 200) {
  return String(v == null ? "" : v).replace(/\s+/g, " ").trim().slice(0, max);
}

function slugify(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9-]+/g, "").slice(0, 64);
}

function bidIncrement(current) {
  if (current < 1000) return 50;
  if (current < 10000) return 100;
  if (current < 50000) return 250;
  if (current < 250000) return 500;
  return 1000;
}

function initialsOf(name) {
  const parts = cleanStr(name, 80).split(/\s+/).filter(Boolean);
  if (!parts.length) return "B.";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase() + ".";
  return `${parts[0][0].toUpperCase()}.${parts[parts.length - 1][0].toUpperCase()}.`;
}

function summarizeLedger(listing, ledger) {
  const entries = (ledger?.entries || []).slice();
  const bids = entries.filter((e) => e.action === "bid").sort((a, b) => b.amount - a.amount);
  const reservations = entries.filter((e) => e.action === "buy_now");
  const currentHigh = bids.length ? bids[0].amount : null;
  const baseFloor = listing?.price || 0;
  const minNext = currentHigh != null ? currentHigh + bidIncrement(currentHigh) : baseFloor;
  return {
    listing_id: listing.id,
    sale_mode: listing.sale_mode,
    status: listing.status,
    starting_bid: listing.sale_mode === "auction" ? listing.price : null,
    buy_now_price: listing.buy_now_price ?? (listing.sale_mode === "buy_now" ? listing.price : null),
    bid_count: bids.length,
    current_high_bid: currentHigh,
    minimum_next_bid: listing.sale_mode === "auction" ? minNext : null,
    reservation_count: reservations.length,
    checkout_url: checkoutUrl(listing.checkout_url),
    recent_bids: bids.slice(0, 20).map((b) => ({
      code: b.code,
      bidder: b.initials,
      amount: b.amount,
      created_at: b.created_at,
    })),
  };
}

function receipt(listing, ledger, entry) {
  const summary = summarizeLedger(listing, ledger);
  const linksToEscrow = entry.action === "buy_now" && listing.status === "active";
  const label = { bid: "Auction bid", buy_now: "Buy It Now request", offer: "Written offer" }[entry.action];
  return jsonResp({
    ok: true, confirmation_code: entry.code, action: entry.action, amount: entry.amount,
    checkout_url: linksToEscrow ? checkoutUrl(listing.checkout_url) : null,
    escrow_notes: listing.escrow_notes || null,
    seller_contact_name: listing.contact_name, seller_brokerage: listing.brokerage || null, summary,
    message: label + " recorded at $" + entry.amount.toLocaleString("en-US") + ". " +
      (entry.action === "buy_now" ? "Confirm the reservation and escrow instructions with the seller or closing professional." : ""),
  }, 201);
}

export async function OPTIONS() {
  return jsonResp({ ok: true }, 204);
}

export async function GET(request) {
  try {
    const url = new URL(request.url);
    const id = slugify(url.searchParams.get("listing"));
    if (!id) return jsonResp({ error: "Provide ?listing=<id>." }, 400);
    const listing = (await readDirect(LISTING_PREFIX + id + ".json"))?.value;
    if (!listing) return jsonResp({ error: "Listing not found." }, 404);
    const ledger = (await readDirect(OFFER_PREFIX + id + ".json"))?.value;
    return jsonResp(summarizeLedger(listing, ledger), 200);
  } catch (err) {
    console.error("[offers GET] error:", err);
    return jsonResp({ error: "Unable to fetch bid status." }, 502);
  }
}

export async function POST(request) {
  try {
    if (!process.env.BLOB_READ_WRITE_TOKEN) {
      return jsonResp({ error: "Bidding/reservation storage is not configured." }, 503);
    }
    const body = await request.json().catch(() => null);
    if (!body || typeof body !== "object") return jsonResp({ error: "JSON body required." }, 400);
    if (body.website_hp) return jsonResp({ error: "Spam check rejected." }, 400);

    const id = slugify(body.listing_id || body.listing);
    const action = cleanStr(body.action || "bid", 20).toLowerCase();
    if (!id || !["bid", "buy_now", "offer"].includes(action)) {
      return jsonResp({ error: "Provide listing_id and action ('bid', 'buy_now', or 'offer')." }, 400);
    }

    const buyerName = cleanStr(body.buyer_name, 120);
    const buyerEmail = cleanStr(body.buyer_email, 160);
    const buyerPhone = cleanStr(body.buyer_phone, 40);
    if (!buyerName || !buyerEmail || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(buyerEmail)) {
      return jsonResp({ error: "Provide buyer_name and a valid buyer_email." }, 400);
    }

    const requestKey = cleanStr(body.request_key, 90);
    const fingerprint = requestKey ? crypto.createHash("sha256")
      .update(JSON.stringify([requestKey, action, buyerEmail.toLowerCase(), body.amount ?? null])).digest("hex") : null;
    const ledgerPath = OFFER_PREFIX + id + ".json";
    for (let attempt = 0; attempt < 4; attempt++) {
      const listing = (await readDirect(LISTING_PREFIX + id + ".json"))?.value;
      if (!listing) return jsonResp({ error: "Listing not found." }, 404);
      const stored = await readDirect(ledgerPath);
      const ledger = stored?.value || { listing_id: id, entries: [] };
      const prior = fingerprint && ledger.entries.find((entry) => entry.request_hash === fingerprint);
      if (prior) return receipt(listing, ledger, prior);
      if (listing.status !== "active") return jsonResp({ error: "This listing is no longer accepting buyer requests." }, 409);
      if (action === "bid" && listing.sale_mode !== "auction") {
        return jsonResp({ error: "Use Buy It Now or send a written offer for this listing." }, 400);
      }
      if (action !== "offer" && listing.sale_mode === "auction" && listing.deadline && Date.parse(listing.deadline) <= Date.now()) {
        return jsonResp({ error: "The auction has closed." }, 409);
      }
      const summary = summarizeLedger(listing, ledger);
      const amount = action === "buy_now" ? summary.buy_now_price : Math.round(Number(body.amount) * 100) / 100;
      if (!Number.isSafeInteger(Math.round(amount * 100)) || !(amount > 0)) {
        return jsonResp({ error: action === "buy_now" ? "No Buy It Now price is available." : "Provide a positive dollar amount." }, 400);
      }
      if (action === "bid" && amount < summary.minimum_next_bid) {
        return jsonResp({ error: "The bid is below the current minimum.", minimum_next_bid: summary.minimum_next_bid }, 409);
      }
      const prefix = { bid: "BID", buy_now: "BUY", offer: "OFR" }[action];
      const entry = {
        code: prefix + "-" + crypto.randomBytes(4).toString("hex").toUpperCase(), action, amount,
        initials: initialsOf(buyerName), buyer_name: buyerName, buyer_email: buyerEmail, buyer_phone: buyerPhone,
        financing: cleanStr(body.financing || "cash", 40), notes: cleanStr(body.notes, 500),
        created_at: new Date().toISOString(), ...(fingerprint ? { request_hash: fingerprint } : {}),
      };
      const updated = { ...ledger, entries: [...ledger.entries, entry] };
      try {
        await writeDirect(ledgerPath, updated, stored?.etag);
        return receipt(listing, updated, entry);
      } catch (err) {
        if (!(err instanceof BlobPreconditionFailedError || !stored && err instanceof BlobError && /already exists|allowOverwrite/i.test(err.message))) throw err;
      }
    }
    return jsonResp({ error: "New activity changed this listing. Refresh and try again." }, 409);
  } catch (err) {
    console.error("[offers POST] error:", err);
    return jsonResp({ error: "Unable to record bid or reservation." }, 502);
  }
}
