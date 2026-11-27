/**
 * Landosaur Agent-First Direct Listing API (Vercel Fluid Compute + Vercel Blob).
 *
 * Designed to be the easiest place on earth for landowners, real estate agents, and AI agents
 * (Claude, ChatGPT, Codex, Gemini, Antigravity, cURL) to list land across all 50 U.S. states:
 *   - GET  /api/listings/              -> All active direct owner/agent listings (starts empty; zero fake listings)
 *   - GET  /api/listings/?id=<id>      -> Single direct listing with live federal X-Ray & bid summary
 *   - POST /api/listings/              -> Publish a Buy It Now or Auction land listing; auto-enriched via 9-agency Federal X-Ray
 *   - PATCH /api/listings/?id=<id>     -> Update status (active / under_contract / sold / withdrawn) with seller edit_token
 */
import crypto from "node:crypto";
import { list, put } from "@vercel/blob";
import { runXray } from "./xray.js";

const PREFIX = "direct/listings/";
const BROWSER_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

function jsonResp(body, status = 200, cache = "no-store") {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cache,
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}

function cleanStr(v, max = 200) {
  return String(v == null ? "" : v).replace(/\s+/g, " ").trim().slice(0, max);
}

function posNum(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function slugify(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 42);
}

function sha256(s) {
  return crypto.createHash("sha256").update(String(s)).digest("hex");
}

function safeCheckoutUrl(raw) {
  const s = cleanStr(raw, 400);
  if (!s) return null;
  try {
    const u = new URL(s);
    if (u.protocol === "https:") return u.toString();
  } catch {
    return null;
  }
  return null;
}

async function geocodeLocation(q) {
  const text = cleanStr(q, 160);
  if (!text) return null;
  const cm = text.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,\s]+\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (cm) {
    const la = Number(cm[1]);
    const lo = Number(cm[2]);
    if (la >= 18 && la <= 72 && lo >= -180 && lo <= -65) return { lat: la, lon: lo, label: text };
  }
  try {
    const u =
      "https://nominatim.openstreetmap.org/search?" +
      new URLSearchParams({ q: text, format: "jsonv2", countrycodes: "us", limit: "1" });
    const r = await fetch(u, {
      signal: AbortSignal.timeout(5500),
      headers: { "User-Agent": "landosaur-listing-api/1.0 (+https://landosaur.com)" },
    });
    if (r.ok) {
      const arr = await r.json();
      if (Array.isArray(arr) && arr[0]?.lat && arr[0]?.lon) {
        return { lat: Number(arr[0].lat), lon: Number(arr[0].lon), label: arr[0].display_name || text };
      }
    }
  } catch {
    // ignore
  }
  return null;
}

function publicView(item) {
  const out = { ...item };
  delete out.edit_token_hash;
  delete out.contact_email;
  delete out.contact_phone;
  out.has_contact = true;
  return out;
}

async function readBlobJson(url) {
  const r = await fetch(url, { headers: { "User-Agent": BROWSER_UA }, cache: "no-store" });
  if (!r.ok) return null;
  return r.json();
}

async function loadAllDirectListings() {
  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    return { configured: false, listings: [] };
  }
  const { blobs } = await list({ prefix: PREFIX, limit: 500 });
  const settled = await Promise.allSettled(blobs.map((b) => readBlobJson(b.url)));
  const items = [];
  for (const s of settled) {
    if (s.status === "fulfilled" && s.value && s.value.id) items.push(s.value);
  }
  items.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  return { configured: true, listings: items };
}

async function loadOneListing(id) {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return null;
  const safeId = slugify(id);
  if (!safeId) return null;
  const { blobs } = await list({ prefix: `${PREFIX}${safeId}.json`, limit: 5 });
  const match = blobs.find((b) => b.pathname === `${PREFIX}${safeId}.json`);
  if (!match) return null;
  return readBlobJson(match.url);
}

export async function OPTIONS() {
  return jsonResp({ ok: true }, 204);
}

export async function GET(request) {
  try {
    const url = new URL(request.url);
    const id = url.searchParams.get("id");
    if (id) {
      const item = await loadOneListing(id);
      if (!item) return jsonResp({ error: "Direct listing not found." }, 404);
      return jsonResp({ listing: publicView(item) }, 200, "public, s-maxage=15, stale-while-revalidate=60");
    }

    const { configured, listings } = await loadAllDirectListings();
    const stateFilter = cleanStr(url.searchParams.get("state"), 4).toUpperCase();
    const modeFilter = cleanStr(url.searchParams.get("sale_mode"), 20).toLowerCase();
    const activeOnly = url.searchParams.get("include_closed") !== "1";

    const filtered = listings
      .filter((x) => (!activeOnly ? true : x.status === "active"))
      .filter((x) => (!stateFilter ? true : x.state === stateFilter))
      .filter((x) => (!modeFilter ? true : x.sale_mode === modeFilter))
      .map(publicView);

    return jsonResp(
      {
        storage_configured: configured,
        count: filtered.length,
        listings: filtered,
      },
      200,
      "public, s-maxage=15, stale-while-revalidate=60"
    );
  } catch (err) {
    console.error("[listings GET] error:", err);
    return jsonResp({ error: "Unable to load direct listings right now." }, 502);
  }
}

export async function POST(request) {
  try {
    if (!process.env.BLOB_READ_WRITE_TOKEN) {
      return jsonResp({ error: "Listing storage is not configured on this environment." }, 503);
    }
    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResp({ error: "Request body must be valid JSON." }, 400);
    }
    if (!body || typeof body !== "object") {
      return jsonResp({ error: "JSON object required." }, 400);
    }
    // Simple honeypot anti-spam field (ignored by legitimate agents)
    if (body.website_hp) {
      return jsonResp({ error: "Spam check rejected." }, 400);
    }

    let lat = Number(body.lat);
    let lon = Number(body.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      const geo = await geocodeLocation(body.location || body.address || "");
      if (geo) {
        lat = geo.lat;
        lon = geo.lon;
      }
    }
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < 18 || lat > 72 || lon < -180 || lon > -65) {
      return jsonResp(
        { error: "Provide valid U.S. coordinates (lat, lon) or a U.S. location/address string." },
        400
      );
    }

    const saleMode = cleanStr(body.sale_mode || "buy_now", 20).toLowerCase();
    if (saleMode !== "buy_now" && saleMode !== "auction") {
      return jsonResp({ error: "sale_mode must be 'buy_now' or 'auction'." }, 400);
    }

    const acres = posNum(body.acres);
    if (!acres || acres > 500000) {
      return jsonResp({ error: "Provide a positive acreage (acres > 0)." }, 400);
    }

    const price = saleMode === "buy_now" ? posNum(body.price) : posNum(body.starting_bid ?? body.price);
    if (!price || price > 500000000) {
      return jsonResp(
        { error: saleMode === "buy_now" ? "Provide a positive Buy It Now price." : "Provide a positive auction starting_bid." },
        400
      );
    }

    const buyNowPrice = saleMode === "auction" ? posNum(body.buy_now_price) : price;
    const contactName = cleanStr(body.contact_name, 120);
    const contactEmail = cleanStr(body.contact_email, 160);
    if (!contactName || !contactEmail || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(contactEmail)) {
      return jsonResp({ error: "Provide contact_name and a valid contact_email." }, 400);
    }

    let auctionEnd = null;
    if (saleMode === "auction") {
      const rawEnd = cleanStr(body.auction_end, 40);
      if (rawEnd) {
        const dt = new Date(rawEnd);
        if (Number.isNaN(dt.getTime()) || dt.getTime() <= Date.now()) {
          return jsonResp({ error: "auction_end must be a valid future ISO date/time." }, 400);
        }
        auctionEnd = dt.toISOString();
      } else {
        // Default 14-day auction window when agent omits explicit cutoff
        auctionEnd = new Date(Date.now() + 14 * 86400 * 1000).toISOString();
      }
    }

    // Auto-enrich via our 9-agency Live Federal Parcel X-Ray!
    const xray = await runXray(lat, lon);
    const stateCode = cleanStr(body.state || xray?.county?.state_code || "", 2).toUpperCase();
    const countyName = cleanStr(body.county || xray?.county?.county_name || "County not stated", 80);
    if (!stateCode) {
      return jsonResp({ error: "Could not determine U.S. state from coordinates; include 2-letter state code." }, 400);
    }

    const defaultTitle = `${acres % 1 === 0 ? acres : acres.toFixed(2)} Acres in ${countyName}, ${stateCode} (${
      saleMode === "auction" ? "Auction" : "Buy It Now"
    })`;
    const title = cleanStr(body.title, 140) || defaultTitle;
    const shortRand = crypto.randomBytes(3).toString("hex");
    const id = `dir-${stateCode.toLowerCase()}-${slugify(countyName).slice(0, 14) || "land"}-${shortRand}`;
    const editToken = crypto.randomBytes(16).toString("hex");

    const sellerType = cleanStr(body.seller_type || "owner", 20).toLowerCase() === "agent" ? "agent" : "owner";
    const listing = {
      id,
      direct: true,
      status: "active",
      sale_mode: saleMode,
      title,
      state: stateCode,
      county: countyName,
      locality: cleanStr(body.locality || "", 80),
      address: cleanStr(body.address || "", 140),
      apn: cleanStr(body.apn || "", 60),
      acres: Math.round(acres * 10000) / 10000,
      price: Math.round(price * 100) / 100,
      price_kind: saleMode === "auction" ? "min_bid" : "cash",
      buy_now_price: buyNowPrice ? Math.round(buyNowPrice * 100) / 100 : null,
      reserve_price: posNum(body.reserve_price),
      deadline: auctionEnd,
      lat: Math.round(lat * 100000) / 100000,
      lon: Math.round(lon * 100000) / 100000,
      zoning: cleanStr(body.zoning || "", 80),
      road_access: cleanStr(body.road_access || "", 120),
      utilities: cleanStr(body.utilities || "", 160),
      financing_offered: Boolean(body.financing_offered),
      notes: cleanStr(body.notes || "", 1200),
      seller_type: sellerType,
      contact_name: contactName,
      contact_email: contactEmail,
      contact_phone: cleanStr(body.contact_phone || "", 40),
      brokerage: cleanStr(body.brokerage || "", 120),
      agent_license: cleanStr(body.agent_license || "", 60),
      checkout_url: safeCheckoutUrl(body.checkout_url),
      escrow_notes: cleanStr(body.escrow_notes || "", 300),
      submitted_by_agent: cleanStr(body.submitted_by_agent || "web", 60),
      bid_count: 0,
      current_high_bid: null,
      created_at: new Date().toISOString(),
      edit_token_hash: sha256(editToken),
      xray_snapshot: {
        elevation_ft: xray?.usgs?.elevation_ft ?? null,
        slope_pct: xray?.usgs?.slope_pct ?? null,
        terrain_class: xray?.usgs?.terrain_class ?? null,
        fema_zone: xray?.fema?.zone ?? null,
        fema_sfha: xray?.fema?.sfha ?? null,
        wetlands_100m: xray?.nwi?.within_100m ?? null,
        soil_drainage: xray?.soil?.drainage_class ?? null,
        nearest_road_ft: xray?.roads?.nearest_road_ft ?? null,
        nearest_road_name: xray?.roads?.nearest_road_name ?? null,
        public_land_1km: xray?.public_land?.units?.[0]?.name ?? null,
        wildfire_risk: xray?.hazards?.wildfire ?? null,
        annual_sun_hours: xray?.climate?.annual_sun_hours ?? null,
        hardiness_zone: xray?.climate?.hardiness_zone ?? null,
        county_benchmark_per_acre: xray?.county?.benchmark_usd_per_acre ?? null,
      },
    };

    await put(`${PREFIX}${id}.json`, JSON.stringify(listing, null, 2), {
      access: "public",
      contentType: "application/json",
      addRandomSuffix: false,
      allowOverwrite: true,
    });

    return jsonResp(
      {
        ok: true,
        id,
        url: `https://landosaur.com/direct/?id=${encodeURIComponent(id)}`,
        edit_token: editToken,
        listing: publicView(listing),
        message: "Published live on Landosaur and enriched with 9 live federal GIS signals. Save your edit_token to update or mark sold.",
      },
      201
    );
  } catch (err) {
    console.error("[listings POST] error:", err);
    return jsonResp({ error: "Failed to publish listing." }, 502);
  }
}

export async function PATCH(request) {
  try {
    if (!process.env.BLOB_READ_WRITE_TOKEN) {
      return jsonResp({ error: "Storage unavailable." }, 503);
    }
    const url = new URL(request.url);
    const id = url.searchParams.get("id");
    const body = await request.json().catch(() => null);
    if (!id || !body) return jsonResp({ error: "Provide ?id=... and JSON body." }, 400);
    const item = await loadOneListing(id);
    if (!item) return jsonResp({ error: "Listing not found." }, 404);
    const token = cleanStr(body.edit_token || request.headers.get("authorization")?.replace(/^Bearer\s+/i, ""), 128);
    if (!token || sha256(token) !== item.edit_token_hash) {
      return jsonResp({ error: "Invalid edit_token." }, 403);
    }
    const allowed = new Set(["active", "under_contract", "sold", "withdrawn"]);
    if (body.status && allowed.has(body.status)) item.status = body.status;
    if (body.price != null && posNum(body.price)) item.price = Math.round(posNum(body.price) * 100) / 100;
    if (body.buy_now_price != null && posNum(body.buy_now_price)) {
      item.buy_now_price = Math.round(posNum(body.buy_now_price) * 100) / 100;
    }
    if (body.checkout_url !== undefined) {
      const cu = cleanStr(body.checkout_url, 500);
      item.checkout_url = !cu ? null : isSafeHttpsUrl(cu) ? cu : item.checkout_url;
    }
    if (body.escrow_notes != null) item.escrow_notes = cleanStr(body.escrow_notes, 600);
    if (body.notes != null) item.notes = cleanStr(body.notes, 1200);
    item.updated_at = new Date().toISOString();

    await put(`${PREFIX}${item.id}.json`, JSON.stringify(item, null, 2), {
      access: "public",
      contentType: "application/json",
      addRandomSuffix: false,
      allowOverwrite: true,
    });
    return jsonResp({ ok: true, listing: publicView(item) }, 200);
  } catch (err) {
    console.error("[listings PATCH] error:", err);
    return jsonResp({ error: "Unable to update listing." }, 502);
  }
}
