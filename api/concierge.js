// Landosaur Land Agent & Acquisition Concierge API ($20 Initiation + Transparent 10% Transfer Fee)
// POST /api/concierge/ — Initiates acquisition for ANY listed Landosaur parcel OR ANY unlisted/off-market parcel across all 50 states.
// GET  /api/concierge/?code=AGT-... — Check real-time status of an acquisition request.

import { get, put } from "@vercel/blob";
import crypto from "node:crypto";
import { LISTING_PREFIX, readDirect } from "../lib/direct-store.js";
import { loadOfficialInventory } from "../lib/official-inventory.mjs";
import "../site/availability.js";
import { geocodeUS, runXray } from "./xray.js";

const { closeExpired } = globalThis.LandosaurAvailability;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const PREFIX = "concierge-orders/";
export const ORDER_CODE = /^AGT-[A-F0-9]{8}$/;
const ORDER_STEPS = ["dossier_opened", "initiation_confirmed", "diligence", "outreach", "transfer"];
const STATUS_STAGE = new Map([
  ["awaiting_initiation_payment", 0],
  ["received_pending_invoice", 0],
  ["paid_active_diligence", 2],
  ["outreach_active", 3],
  ["transfer_in_progress", 4],
  ["closed", 5],
]);

export async function readOrder(code) {
  if (!ORDER_CODE.test(code)) return null;
  const record = await get(PREFIX + code + ".json", { access: "public", useCache: false });
  if (!record || record.statusCode !== 200) return null;
  return { order: await new Response(record.stream).json(), etag: record.blob.etag };
}

export function writeOrder(order, etag) {
  return put(PREFIX + order.confirmation_code + ".json", JSON.stringify(order, null, 2), {
    access: "public",
    contentType: "application/json",
    addRandomSuffix: false,
    ...(etag ? { ifMatch: etag } : { allowOverwrite: false }),
  });
}

function publicProgress(order) {
  const events = Array.isArray(order.timeline) ? order.timeline : [];
  const timestamps = Object.fromEntries(events
    .filter((event) => ORDER_STEPS.includes(event?.step) && Number.isFinite(Date.parse(event.at)))
    .map((event) => [event.step, event.at]));
  const stage = Math.max(STATUS_STAGE.get(order.status) ?? 0, order.paid_at ? 2 : 0);
  return ORDER_STEPS.map((id, index) => ({
    id,
    state: stage === 0 && index === 0 || stage > index ? "complete" :
      (stage === 0 && index === 1 || stage === index ? "current" : "pending"),
    at: timestamps[id] || (index === 0 ? order.created_at : index === 1 ? order.paid_at : null) || null,
  }));
}

function publicSummary(order) {
  const info = order.xray_summary;
  if (!info || typeof info !== "object") return null;
  return Object.fromEntries(["county_name", "state_code", "elevation_ft", "fema_zone", "wetlands_100m",
    "nearest_road_ft", "county_benchmark_per_acre"].map((field) => [field, info[field] ?? null]));
}
const VALID_SERVICES = new Set([
  "listed_acquisition",
  "unlisted_outreach",
  "auction_proxy",
  "landbank_application",
  "diligence_packet",
  "direct_closing",
  "custom_sourcing",
]);

function jsonResp(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, max-age=0", "CDN-Cache-Control": "no-store",
      ...CORS,
    },
  });
}

export function OPTIONS() {
  return new Response(null, { status: 204, headers: CORS });
}

function cleanStr(v, max = 300) {
  return String(v == null ? "" : v).replace(/[\u0000-\u001F\u007F]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
}

function posNum(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

async function readAcquisitionParcel(id) {
  if (!/^[a-z0-9][a-z0-9-]{0,119}$/.test(id)) return null;
  if (id.startsWith("dir-")) {
    const listing = (await readDirect(`${LISTING_PREFIX}${id}.json`))?.value;
    if (listing?.id !== id || listing.status !== "active") return null;
    const auction = listing.sale_mode === "auction";
    if (auction && !(Date.parse(listing.deadline) > Date.now())) return null;
    const { title, state, county, apn, acres, lat, lon } = listing;
    return { id, title, state, county, apn, acres, lat, lon,
      price: posNum(listing.price), price_kind: auction ? "min_bid" : "cash", is_direct: true };
  }
  const row = (await loadOfficialInventory()).find((item) => item[0] === id);
  if (!row || !closeExpired(row, Date.now())[8]) return null;
  const [, lat, lon, state, price, price_kind, acres, , , title, county, apn] = row;
  return { id, title, state, county, apn, acres, lat, lon, price, price_kind, is_direct: false };
}

function buildStripeUrl(orderId, buyerEmail, parcelLabel) {
  const base = (process.env.STRIPE_LAND_AGENT_LINK || "").trim();
  if (!base || !base.startsWith("https://")) return null;
  try {
    const u = new URL(base);
    u.searchParams.set("client_reference_id", orderId);
    if (buyerEmail) u.searchParams.set("prefilled_email", buyerEmail);
    if (parcelLabel) u.searchParams.set("utm_content", parcelLabel.slice(0, 60));
    return u.toString();
  } catch {
    return null;
  }
}

export async function GET(request) {
  try {
    const url = new URL(request.url);
    const code = cleanStr(url.searchParams.get("code"), 32).toUpperCase();
    const configured = Boolean(process.env.BLOB_READ_WRITE_TOKEN);
    const stripeReady = Boolean((process.env.STRIPE_LAND_AGENT_LINK || "").trim());

    if (!code && url.searchParams.has("parcel_id")) {
      const parcel = await readAcquisitionParcel(url.searchParams.get("parcel_id").trim().toLowerCase());
      return parcel ? jsonResp({ ok: true, parcel }) : jsonResp({ error: "Active Landosaur parcel not found." }, 404);
    }
    if (!code) {
      return jsonResp({
        ok: true,
        storage_configured: configured,
        stripe_checkout_configured: stripeReady,
        initiation_fee_usd: 20,
        concierge_fee_pct: 10,
        services: Array.from(VALID_SERVICES),
      });
    }
    if (!configured) {
      return jsonResp({ error: "Order storage unavailable." }, 503);
    }
    const stored = await readOrder(code);
    if (!stored) return jsonResp({ error: "Order confirmation code not found." }, 404);
    const { order } = stored;
    // Return public-safe status view (no raw email/phone leak)
    return jsonResp({
      ok: true,
      order: {
        confirmation_code: order.confirmation_code,
        status: order.status,
        service_type: order.service_type,
        parcel_id: order.parcel_id,
        parcel_title: order.parcel_title,
        county: order.county,
        state: order.state,
        apn: order.apn,
        official_price: order.official_price,
        seller_price: order.seller_price ?? null,
        price_kind: order.price_kind ?? null,
        estimated_base_price: order.official_price ?? order.seller_price ?? order.max_budget ?? null,
        concierge_fee_10pct: order.concierge_fee_10pct,
        estimated_turnkey_total: order.estimated_turnkey_total,
        initiation_fee_usd: order.initiation_fee_usd,
        created_at: order.created_at,
        paid_at: order.paid_at || null,
        progress: publicProgress(order),
        xray_summary: publicSummary(order),
        stripe_checkout_url: STATUS_STAGE.get(order.status) === 0 && !order.paid_at
          ? buildStripeUrl(order.confirmation_code, "", order.parcel_title) : null,
      },
    });
  } catch (err) {
    console.error("[concierge GET] error:", err);
    return jsonResp({ error: "Unable to check order status right now." }, 502);
  }
}

function coordinates(lat, lon) {
  if (lat == null || lon == null || lat === "" || lon === "") return null;
  const pair = [Number(lat), Number(lon)];
  return pair[0] >= 18 && pair[0] <= 72 && pair[1] >= -180 && pair[1] <= -65 ? pair : null;
}

function drawnBoundary(value) {
  if (!Array.isArray(value) || value.length < 3 || value.length > 300) return null;
  return value.every((point) => Array.isArray(point) && point.length === 2 && coordinates(point[1], point[0])) ? value : null;
}

export async function openOrder(request, {
  configured = Boolean(process.env.BLOB_READ_WRITE_TOKEN),
  lookup = readAcquisitionParcel, xrayAt = runXray, write = writeOrder,
} = {}) {
  try {
    if (!configured) {
      return jsonResp({ error: "Concierge order storage is not configured." }, 503);
    }
    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResp({ error: "Request body must be valid JSON." }, 400);
    }
    if (!body || typeof body !== "object") return jsonResp({ error: "JSON object required." }, 400);
    if (body.website_hp) return jsonResp({ error: "Spam check rejected." }, 400);

    const serviceType = cleanStr(body.service_type || "listed_acquisition", 40).toLowerCase();
    if (!VALID_SERVICES.has(serviceType)) {
      return jsonResp({ error: "Invalid service_type." }, 400);
    }

    const buyerName = cleanStr(body.buyer_name, 120);
    const buyerEmail = cleanStr(body.buyer_email, 160);
    const buyerPhone = cleanStr(body.buyer_phone, 40);
    if (!buyerName || !buyerEmail || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(buyerEmail)) {
      return jsonResp({ error: "Provide your full name and a valid email address." }, 400);
    }

    const parcelId = cleanStr(body.parcel_id).toLowerCase() || null;
    const parcel = parcelId ? await lookup(parcelId) : null;
    if (parcelId && !parcel) return jsonResp({ error: "Active Landosaur parcel not found. Check the ID or enter an off-market location." }, 404);

    const apn = parcel?.apn || cleanStr(body.apn, 100) || null;
    let county = parcel?.county || cleanStr(body.county, 80);
    let state = parcel?.state || cleanStr(body.state, 20).toUpperCase().slice(0, 2);
    const location = cleanStr(body.location || body.address, 220);
    let parcelTitle = parcel?.title || cleanStr(body.parcel_title, 200);
    const officialPrice = parcel && !parcel.is_direct ? parcel.price : null;
    const sellerPrice = parcel?.is_direct ? parcel.price : null;
    // Older clients may send their own estimate in official_price for an unlisted property.
    const maxBudget = posNum(body.max_budget || body.offer_amount) ?? (parcel ? null : posNum(body.official_price));
    const acres = parcel?.acres ?? posNum(body.acres);
    const notes = cleanStr(body.notes, 1500);
    const boundary = drawnBoundary(body.boundary);
    const financing = cleanStr(body.financing || "cash", 40);
    const submittedByAgent = cleanStr(body.submitted_by_agent, 80) || "landosaur-web";

    let point = coordinates(parcel?.lat, parcel?.lon) || coordinates(body.lat, body.lon);
    if (!parcelId && !apn && !location && !point && serviceType !== "custom_sourcing") {
      return jsonResp({ error: "Provide a Landosaur parcel ID, county APN, address/town, or map coordinates." }, 400);
    }

    if (!point && location) {
      const geo = await geocodeUS(location).catch(() => null);
      if (geo) point = coordinates(geo.lat, geo.lon);
    }
    const [lat, lon] = point ? point.map((v) => Math.round(v * 100000) / 100000) : [null, null];
    let xraySummary = null;
    if (point) {
      const xray = await xrayAt(lat, lon).catch(() => null);
      if (xray) {
        if (!county && xray.county?.county_name) county = xray.county.county_name;
        if (!state && xray.county?.state_code) state = xray.county.state_code;
        xraySummary = {
          county_name: xray.county?.county_name ?? null,
          state_code: xray.county?.state_code ?? null,
          elevation_ft: xray.usgs?.elevation_ft ?? null,
          slope_pct: xray.usgs?.slope_pct ?? null,
          fema_zone: xray.fema?.zone ?? null,
          wetlands_100m: xray.nwi?.within_100m ?? null,
          nearest_road_ft: xray.roads?.nearest_road_ft ?? null,
          county_benchmark_per_acre: xray.county?.benchmark_usd_per_acre ?? null,
        };
      }
    }

    if (!parcelTitle) {
      if (parcelId) parcelTitle = `Parcel ${parcelId}`;
      else if (apn) parcelTitle = `Unlisted APN ${apn}${county ? `, ${county}` : ""}${state ? `, ${state}` : ""}`;
      else if (location) parcelTitle = `${location} (${serviceType.replace(/_/g, " ")})`;
      else parcelTitle = `Custom Land Acquisition Request (${state || "US"})`;
    }

    const baseAmount = officialPrice ?? sellerPrice ?? maxBudget;
    const conciergeFee = baseAmount != null ? Math.round(baseAmount * 0.1 * 100) / 100 : null;
    const turnkeyTotal = baseAmount != null ? Math.round((baseAmount + conciergeFee) * 100) / 100 : null;
    const confirmationCode = `AGT-${crypto.randomBytes(4).toString("hex").toUpperCase()}`;
    const nowIso = new Date().toISOString();

    const order = {
      confirmation_code: confirmationCode,
      status: process.env.STRIPE_LAND_AGENT_LINK ? "awaiting_initiation_payment" : "received_pending_invoice",
      service_type: serviceType,
      initiation_fee_usd: 20,
      concierge_fee_pct: 10,
      parcel_id: parcelId,
      parcel_title: parcelTitle,
      parcel_url: parcelId ? (parcel.is_direct ? `https://landosaur.com/direct/?id=${encodeURIComponent(parcelId)}` :
        `https://landosaur.com/land/${encodeURIComponent(parcelId)}/`) : null,
      apn,
      location: location || null,
      county: county || null,
      state: state || null,
      lat,
      lon,
      acres,
      ...(boundary ? { boundary } : {}),
      official_price: officialPrice,
      seller_price: sellerPrice,
      price_kind: parcel?.price_kind ?? null,
      max_budget: maxBudget,
      concierge_fee_10pct: conciergeFee,
      estimated_turnkey_total: turnkeyTotal,
      financing,
      buyer_name: buyerName,
      buyer_email: buyerEmail,
      buyer_phone: buyerPhone || null,
      notes: notes || null,
      submitted_by_agent: submittedByAgent,
      xray_summary: xraySummary,
      created_at: nowIso,
      timeline: [{ step: "dossier_opened", at: nowIso }],
    };

    await write(order);

    const stripeCheckoutUrl = buildStripeUrl(confirmationCode, buyerEmail, parcelTitle);

    return jsonResp(
      {
        ok: true,
        confirmation_code: confirmationCode,
        status: order.status,
        initiation_fee_usd: 20,
        concierge_fee_pct: 10,
        official_price: officialPrice,
        seller_price: sellerPrice,
        price_kind: order.price_kind,
        estimated_base_price: baseAmount,
        concierge_fee_10pct: conciergeFee,
        estimated_turnkey_total: turnkeyTotal,
        stripe_checkout_url: stripeCheckoutUrl,
        tracking_url: `https://landosaur.com/services/?code=${confirmationCode}#track-order`,
        xray_summary: xraySummary,
        message: stripeCheckoutUrl
          ? "Acquisition dossier created. Complete the $20 Land Agent initiation checkout on Stripe to activate county verification, outreach, and transfer coordination."
          : "Acquisition dossier logged (" +
            confirmationCode +
            "). Our Land Agent desk will send your $20 Stripe initiation link to " +
            buyerEmail +
            " to begin county title/redemption verification and transfer coordination.",
      },
      201
    );
  } catch (err) {
    console.error("[concierge POST] error:", err);
    return jsonResp({ error: "Unable to record acquisition request right now." }, 502);
  }
}

export const POST = (request) => openOrder(request);
