// Landosaur Saved-Search & Instant Land Alerts API (Vercel Fluid Compute + Vercel Blob)
// POST /api/alerts/                     -> Save a custom search alert (state, mode, max_price, min_acres, below_benchmark, q, buyer_email)
// GET  /api/alerts/?id=ALR-...          -> Live JSON matches for that saved search
// GET  /api/alerts/?id=ALR-...&format=atom -> Personalized RFC-4287 Atom/RSS feed for RSS readers, Slack, Zapier, & AI agents
// GET  /api/alerts/                     -> Service health & schema metadata

import crypto from "node:crypto";
import { list, put } from "@vercel/blob";
import { loadOfficialInventory } from "../lib/official-inventory.mjs";

import "../site/geo.js";
import "../site/availability.js";
const { closeExpired } = globalThis.LandosaurAvailability;
const { decode, matcher, measure } = globalThis.LandosaurGeo;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const ALERTS_PREFIX = "saved-alerts/";
const DIRECT_PREFIX = "direct/listings/";

function jsonResp(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store, max-age=0", "CDN-Cache-Control": "no-store", ...CORS },
  });
}

export function OPTIONS() {
  return new Response(null, { status: 204, headers: CORS });
}

function cleanStr(v, max = 180) {
  return String(v == null ? "" : v).replace(/[\u0000-\u001F\u007F]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
}

function posNum(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function xmlEsc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

async function loadDirectRows() {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return [];
  try {
    const res = await list({ prefix: DIRECT_PREFIX, limit: 200 });
    const items = await Promise.all(
      res.blobs
        .filter((b) => b.pathname.endsWith(".json"))
        .map(async (b) => {
          try {
            const r = await fetch(b.url, { cache: "no-store", signal: AbortSignal.timeout(5000) });
            return r.ok ? await r.json() : null;
          } catch {
            return null;
          }
        })
    );
    return items.filter(Boolean).map((it) => [
      it.id,
      it.lat,
      it.lon,
      it.state,
      it.price,
      it.sale_mode === "auction" ? "min_bid" : "cash",
      it.acres,
      it.sale_mode === "auction" ? "auction_open" : "listed",
      it.status === "active" ? 1 : 0,
      it.title,
      it.county || "",
      it.apn || "",
      (it.deadline || "").slice(0, 10),
      1,
      null,
      it.sale_mode === "auction" ? Date.parse(it.deadline) : null,
    ]);
  } catch {
    return [];
  }
}

function filterRows(rows, crit) {
  const st = (crit.state || "").toUpperCase();
  const mode = (crit.mode || "").toLowerCase();
  const maxP = posNum(crit.max_price);
  const minAc = posNum(crit.min_acres);
  const q = (crit.q || "").toLowerCase();
  const belowBench = Boolean(crit.below_benchmark);
  const area = crit.area ? matcher(decode(crit.area)) : null;

  const out = [];
  const now = Date.now();
  for (const row of rows) {
    const r = closeExpired(row, now);
    if (!r[8] || area && !area(r[2], r[1])) continue;
    if (st && r[3] !== st) continue;
    if (maxP != null && (r[4] == null || r[4] > maxP)) continue;
    if (minAc != null && (!r[6] || r[6] < minAc)) continue;
    if (belowBench && (r[14] == null || r[14] >= 0)) continue;
    if (q && `${r[9]} ${r[10]} ${r[11]} ${r[3]}`.toLowerCase().indexOf(q) < 0) continue;
    const isCash = r[5] === "cash";
    const isAuc = r[5] === "min_bid" || r[7] === "auction_open" || r[7] === "auction_terms";
    const isNone = !isCash && !isAuc;
    const isDirect = Boolean(r[13]);
    if ((mode === "cash" || mode === "buy_now") && !isCash) continue;
    if ((mode === "min_bid" || mode === "auction") && !isAuc) continue;
    if ((mode === "none" || mode === "offer") && !isNone) continue;
    if (mode === "direct" && !isDirect) continue;
    out.push(r);
  }
  out.sort((a, b) => {
    if (belowBench) {
      return (a[14] ?? 999) - (b[14] ?? 999);
    }
    const sa = (a[13] ? 1000 : 0) + (a[4] != null ? 50 : 0) + (a[6] > 0 ? 30 : 0);
    const sb = (b[13] ? 1000 : 0) + (b[4] != null ? 50 : 0) + (b[6] > 0 ? 30 : 0);
    return sb - sa || (a[4] ?? 1e12) - (b[4] ?? 1e12);
  });
  return out;
}

function formatRow(r, origin) {
  const isDirect = Boolean(r[13]);
  const url = isDirect ? `${origin}/direct/?id=${encodeURIComponent(r[0])}` : `${origin}/land/${r[0]}/`;
  const price = r[4] != null ? Number(r[4]) : null;
  const acres = r[6] != null ? Number(r[6]) : null;
  const ppa = price && acres ? Math.round((price / acres) * 100) / 100 : null;
  return {
    id: r[0],
    title: r[9],
    state: r[3],
    county: r[10],
    apn: r[11] || null,
    price,
    price_kind: r[5],
    acres,
    usd_per_acre: ppa,
    vs_county_benchmark_pct: r[14] ?? null,
    status: r[7],
    deadline: r[12] || null,
    lat: r[1],
    lon: r[2],
    is_direct: isDirect,
    url,
    land_agent_url: `${origin}/services/?parcel=${encodeURIComponent(r[0])}&title=${encodeURIComponent(r[9])}${price ? `&price=${price}` : ""}${acres ? `&acres=${acres}` : ""}&county=${encodeURIComponent(r[10] || "")}&state=${encodeURIComponent(r[3] || "")}`,
  };
}

function buildAtomFeed(alert, items, origin, selfUrl) {
  const nowIso = new Date().toISOString();
  const title = alert.label || "Landosaur Saved Search Alert";
  const entries = items
    .slice(0, 60)
    .map((it) => {
      const bits = [];
      if (it.price != null) bits.push(`$${Math.round(it.price).toLocaleString("en-US")} (${it.price_kind})`);
      if (it.acres != null) bits.push(`${it.acres} acres`);
      if (it.usd_per_acre != null) bits.push(`$${Math.round(it.usd_per_acre).toLocaleString("en-US")}/ac`);
      if (it.vs_county_benchmark_pct != null && it.vs_county_benchmark_pct < 0) {
        bits.push(`${Math.abs(it.vs_county_benchmark_pct)}% below county USDA/FHFA benchmark`);
      }
      bits.push(`${it.county}, ${it.state}`);
      return `<entry><title>${xmlEsc(it.title)}</title><link href="${xmlEsc(it.url)}"/><id>${xmlEsc(it.url)}</id><updated>${xmlEsc(nowIso)}</updated><summary>${xmlEsc(bits.join(" · "))}</summary></entry>`;
    })
    .join("");
  return `<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>${xmlEsc(title)} | Landosaur Alerts</title><link href="${xmlEsc(origin + "/")}"/><link rel="self" href="${xmlEsc(selfUrl)}"/><id>${xmlEsc(selfUrl)}</id><updated>${xmlEsc(nowIso)}</updated><author><name>Landosaur</name></author>${entries}</feed>`;
}

export async function GET(request) {
  try {
    const url = new URL(request.url);
    const id = cleanStr(url.searchParams.get("id"), 32).toUpperCase();
    const format = cleanStr(url.searchParams.get("format") || "json", 16).toLowerCase();
    const configured = Boolean(process.env.BLOB_READ_WRITE_TOKEN);

    if (!id) {
      return jsonResp({
        ok: true,
        storage_configured: configured,
        formats: ["json", "atom"],
        usage: "POST /api/alerts/ with {state, mode, max_price, min_acres, below_benchmark, q, buyer_email} to create a live saved search + custom Atom/JSON alert feed.",
      });
    }
    if (!configured) return jsonResp({ error: "Alert storage unavailable." }, 503);
    const res = await list({ prefix: ALERTS_PREFIX, limit: 300 });
    const match = res.blobs.find((b) => b.pathname.endsWith(`/${id}.json`));
    if (!match) return jsonResp({ error: "Saved search alert not found." }, 404);
    const r = await fetch(match.url, { cache: "no-store" });
    if (!r.ok) return jsonResp({ error: "Unable to load saved alert." }, 502);
    const alert = await r.json();

    const origin = url.origin.includes("localhost") ? "https://landosaur.com" : url.origin;
    const [official, direct] = await Promise.all([loadOfficialInventory(), loadDirectRows()]);
    const matches = filterRows(direct.concat(official), alert.criteria || {});
    const formatted = matches.slice(0, 60).map((row) => formatRow(row, origin));

    if (format === "atom" || format === "xml" || format === "rss") {
      const xml = buildAtomFeed(alert, formatted, origin, `${origin}/api/alerts/?id=${id}&format=atom`);
      return new Response(xml, {
        status: 200,
        headers: {
          "Content-Type": "application/atom+xml; charset=utf-8",
          "Cache-Control": "no-store, max-age=0", "CDN-Cache-Control": "no-store",
          ...CORS,
        },
      });
    }

    return jsonResp({
      ok: true,
      alert_id: alert.alert_id,
      label: alert.label,
      criteria: alert.criteria,
      created_at: alert.created_at,
      total_matches: matches.length,
      atom_feed_url: `${origin}/api/alerts/?id=${alert.alert_id}&format=atom`,
      results: formatted,
    });
  } catch (err) {
    console.error("[alerts GET] error:", err);
    return jsonResp({ error: "Unable to load saved-search alert right now." }, 502);
  }
}

export async function POST(request) {
  try {
    if (!process.env.BLOB_READ_WRITE_TOKEN) {
      return jsonResp({ error: "Alert storage is not configured." }, 503);
    }
    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResp({ error: "Request body must be valid JSON." }, 400);
    }
    if (!body || typeof body !== "object") return jsonResp({ error: "JSON object required." }, 400);
    if (body.website_hp) return jsonResp({ error: "Spam check rejected." }, 400);

    const buyerEmail = cleanStr(body.buyer_email, 160);
    if (buyerEmail && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(buyerEmail)) {
      return jsonResp({ error: "Enter a valid email address (or leave blank for RSS/JSON feed only)." }, 400);
    }

    const area = typeof body.area === "string" ? body.area : "";
    if (body.area != null && (!area || area.length > 1200 || !measure(decode(area)))) {
      return jsonResp({ error: "Provide a valid drawn search area." }, 400);
    }
    const criteria = {
      state: cleanStr(body.state, 4).toUpperCase(),
      mode: cleanStr(body.mode, 24).toLowerCase(),
      max_price: posNum(body.max_price),
      min_acres: posNum(body.min_acres),
      below_benchmark: Boolean(body.below_benchmark),
      q: cleanStr(body.q, 100),
      ...(area ? { area } : {}),
    };

    const parts = [];
    if (criteria.state) parts.push(criteria.state);
    else parts.push("All 50 States");
    if (criteria.mode === "cash" || criteria.mode === "buy_now") parts.push("Buy It Now");
    else if (criteria.mode === "min_bid" || criteria.mode === "auction") parts.push("Auctions");
    else if (criteria.mode === "direct") parts.push("Direct");
    if (criteria.below_benchmark) parts.push("Below County Avg");
    if (criteria.max_price) parts.push(`<= $${Math.round(criteria.max_price).toLocaleString("en-US")}`);
    if (criteria.min_acres) parts.push(`${criteria.min_acres}+ ac`);
    if (criteria.q) parts.push(`"${criteria.q}"`);
    if (criteria.area) parts.push("Drawn search area");
    const label = cleanStr(body.label, 120) || parts.join(" · ");

    const alertId = `ALR-${crypto.randomBytes(4).toString("hex").toUpperCase()}`;
    const nowIso = new Date().toISOString();
    const record = {
      alert_id: alertId,
      label,
      criteria,
      buyer_email: buyerEmail || null,
      created_at: nowIso,
    };

    await put(`${ALERTS_PREFIX}${alertId}.json`, JSON.stringify(record, null, 2), {
      access: "public",
      contentType: "application/json",
      addRandomSuffix: false,
      allowOverwrite: false,
    });

    const url = new URL(request.url);
    const origin = url.origin.includes("localhost") ? "https://landosaur.com" : url.origin;
    const landAgentParams = new URLSearchParams({
      service: "custom_sourcing",
      ...(criteria.state ? { state: criteria.state } : {}),
      ...(criteria.max_price ? { price: String(criteria.max_price) } : {}),
      ...(criteria.min_acres ? { acres: String(criteria.min_acres) } : {}),
    });

    return jsonResp(
      {
        ok: true,
        alert_id: alertId,
        label,
        criteria,
        email_registered: Boolean(buyerEmail),
        json_feed_url: `${origin}/api/alerts/?id=${alertId}`,
        atom_feed_url: `${origin}/api/alerts/?id=${alertId}&format=atom`,
        land_agent_url: `${origin}/services/?${landAgentParams.toString()}`,
        message: buyerEmail
          ? `Saved search ${alertId} created for ${buyerEmail}. Subscribe instantly with your live Atom/RSS feed or let our Land Agent actively hunt off-market matches.`
          : `Saved search ${alertId} created. Subscribe to your personalized live Atom/RSS or JSON feed URL anytime.`,
      },
      201
    );
  } catch (err) {
    console.error("[alerts POST] error:", err);
    return jsonResp({ error: "Unable to save search alert right now." }, 502);
  }
}
