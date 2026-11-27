/**
 * Landosaur Live Bidding & Buy-It-Now Checkout / Reservation API (Vercel Fluid Compute + Vercel Blob).
 *
 * Powers real buyer actions on Direct Seller/Agent listings:
 *   - GET  /api/offers/?listing=<id> -> Current bid count, high bid, min next bid, anonymized bid tape (starts honestly at 0!)
 *   - POST /api/offers/              -> Place a live Auction Bid, Buy-It-Now Reservation, or Written Offer
 */
import crypto from "node:crypto";
import { list, put } from "@vercel/blob";

const LISTING_PREFIX = "direct/listings/";
const OFFER_PREFIX = "direct/offers/";

function jsonResp(body, status = 200, cache = "no-store") {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cache,
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

async function readBlobByPath(pathname) {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return null;
  const { blobs } = await list({ prefix: pathname, limit: 5 });
  const match = blobs.find((b) => b.pathname === pathname);
  if (!match) return null;
  const r = await fetch(match.url, { cache: "no-store" });
  return r.ok ? r.json() : null;
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
    checkout_url: listing.checkout_url || null,
    recent_bids: bids.slice(0, 20).map((b) => ({
      code: b.code,
      bidder: b.initials,
      amount: b.amount,
      created_at: b.created_at,
    })),
  };
}

export async function OPTIONS() {
  return jsonResp({ ok: true }, 204);
}

export async function GET(request) {
  try {
    const url = new URL(request.url);
    const id = slugify(url.searchParams.get("listing"));
    if (!id) return jsonResp({ error: "Provide ?listing=<id>." }, 400);
    const listing = await readBlobByPath(`${LISTING_PREFIX}${id}.json`);
    if (!listing) return jsonResp({ error: "Listing not found." }, 404);
    const ledger = await readBlobByPath(`${OFFER_PREFIX}${id}.json`);
    return jsonResp(summarizeLedger(listing, ledger), 200, "no-store");
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

    const listing = await readBlobByPath(`${LISTING_PREFIX}${id}.json`);
    if (!listing) return jsonResp({ error: "Listing not found." }, 404);
    if (listing.status !== "active") {
      return jsonResp({ error: `This parcel is currently marked ${listing.status} and is not accepting new bids.` }, 409);
    }
    if (action === "bid" && listing.sale_mode !== "auction") {
      return jsonResp({ error: "This parcel is a Buy It Now listing; use action='buy_now' or action='offer'." }, 400);
    }
    if (action === "bid" && listing.deadline && new Date(listing.deadline).getTime() <= Date.now()) {
      return jsonResp({ error: "Bidding window has closed for this auction." }, 409);
    }

    const buyerName = cleanStr(body.buyer_name, 120);
    const buyerEmail = cleanStr(body.buyer_email, 160);
    const buyerPhone = cleanStr(body.buyer_phone, 40);
    if (!buyerName || !buyerEmail || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(buyerEmail)) {
      return jsonResp({ error: "Provide buyer_name and a valid buyer_email." }, 400);
    }

    const ledgerPath = `${OFFER_PREFIX}${id}.json`;
    const ledger = (await readBlobByPath(ledgerPath)) || { listing_id: id, entries: [] };
    const summary = summarizeLedger(listing, ledger);

    let amount = Number(body.amount);
    if (action === "buy_now") {
      const bn = listing.buy_now_price ?? (listing.sale_mode === "buy_now" ? listing.price : null);
      if (!bn) return jsonResp({ error: "This auction does not have a Buy It Now price." }, 400);
      amount = bn;
    } else if (action === "bid") {
      if (!Number.isFinite(amount) || amount < summary.minimum_next_bid) {
        return jsonResp(
          {
            error: `Bid must be at least $${Math.round(summary.minimum_next_bid).toLocaleString("en-US")}.`,
            minimum_next_bid: summary.minimum_next_bid,
          },
          400
        );
      }
    } else if (!Number.isFinite(amount) || amount <= 0) {
      return jsonResp({ error: "Provide a positive offer amount." }, 400);
    }

    const prefixCode = action === "bid" ? "BID" : action === "buy_now" ? "BUY" : "OFR";
    const code = `${prefixCode}-${crypto.randomBytes(3).toString("hex").toUpperCase()}`;
    const entry = {
      code,
      action,
      amount: Math.round(amount * 100) / 100,
      initials: initialsOf(buyerName),
      buyer_name: buyerName,
      buyer_email: buyerEmail,
      buyer_phone: buyerPhone,
      financing: cleanStr(body.financing || "cash", 40),
      notes: cleanStr(body.notes || "", 500),
      created_at: new Date().toISOString(),
    };
    ledger.entries.push(entry);

    await put(ledgerPath, JSON.stringify(ledger, null, 2), {
      access: "public",
      contentType: "application/json",
      addRandomSuffix: false,
      allowOverwrite: true,
    });

    // Keep summary fields in sync on listing blob
    if (action === "bid") {
      listing.bid_count = (listing.bid_count || 0) + 1;
      listing.current_high_bid = Math.max(listing.current_high_bid || 0, entry.amount);
      await put(`${LISTING_PREFIX}${id}.json`, JSON.stringify(listing, null, 2), {
        access: "public",
        contentType: "application/json",
        addRandomSuffix: false,
        allowOverwrite: true,
      });
    }

    const updated = summarizeLedger(listing, ledger);
    return jsonResp(
      {
        ok: true,
        confirmation_code: code,
        action,
        amount: entry.amount,
        checkout_url: listing.checkout_url || null,
        escrow_notes: listing.escrow_notes || null,
        seller_contact_name: listing.contact_name,
        seller_brokerage: listing.brokerage || null,
        summary: updated,
        message:
          action === "bid"
            ? `Bid of $${entry.amount.toLocaleString("en-US")} recorded (${code}). You are currently the high bidder.`
            : action === "buy_now"
            ? `Buy It Now reservation recorded (${code}) at $${entry.amount.toLocaleString("en-US")}. ${
                listing.checkout_url
                  ? "Continue to the seller's verified title/escrow checkout link to complete earnest money."
                  : "Seller/agent will finalize closing through a licensed title company or closing attorney."
              }`
            : `Written offer of $${entry.amount.toLocaleString("en-US")} submitted (${code}).`,
      },
      201
    );
  } catch (err) {
    console.error("[offers POST] error:", err);
    return jsonResp({ error: "Unable to record bid or reservation." }, 502);
  }
}
