// Landosaur Agent-Native Two-Sided Land Search API
// GET /api/search/?state=IN&mode=auction&max_price=5000&min_acres=0.2&q=muncie&sort=price_asc&limit=25
// Queries BOTH 23,500+ official public-agency parcels (/data/map.json) AND live Direct Owner/Agent listings (Vercel Blob).

import { list } from "@vercel/blob";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const PREFIX = "direct-listings/";
let cachedOfficial = { at: 0, rows: [] };
const CACHE_TTL_MS = 5 * 60 * 1000;

function jsonResp(body, status = 200, cache = "public, s-maxage=30, stale-while-revalidate=120") {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": cache, ...CORS },
  });
}

export function OPTIONS() {
  return new Response(null, { status: 204, headers: CORS });
}

function classifyMode(r) {
  if (r[13]) return r[5] === "min_bid" ? "direct_auction" : "direct_buy_now";
  if (r[5] === "cash") return "buy_now";
  if (r[5] === "min_bid" || r[7] === "auction_open" || r[7] === "auction_terms") return "auction";
  return "offer";
}

function matchesMode(r, mode) {
  if (!mode || mode === "all") return true;
  if (mode === "buy_now" || mode === "cash") return r[5] === "cash";
  if (mode === "auction" || mode === "min_bid") return r[5] === "min_bid" || r[7] === "auction_open" || r[7] === "auction_terms";
  if (mode === "offer" || mode === "none" || mode === "land_bank") return r[5] === "none" && r[7] !== "auction_open" && r[7] !== "auction_terms";
  if (mode === "direct") return Boolean(r[13]);
  return true;
}

async function loadOfficialRows(origin) {
  const now = Date.now();
  if (cachedOfficial.rows.length && now - cachedOfficial.at < CACHE_TTL_MS) {
    return cachedOfficial.rows;
  }
  const dep = encodeURIComponent(process.env.VERCEL_DEPLOYMENT_ID || String(Math.floor(now / 60000)));
  const res = await fetch(`${origin}/data/map.json?v=${dep}`, {
    headers: { "User-Agent": "Landosaur-Search/1.0" },
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`map.json HTTP ${res.status}`);
  const data = await res.json();
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  cachedOfficial = { at: now, rows };
  return rows;
}

async function loadDirectRows() {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return [];
  try {
    const res = await list({ prefix: PREFIX, limit: 200 });
    const items = await Promise.all(
      res.blobs
        .filter((b) => b.pathname.endsWith(".json"))
        .map(async (b) => {
          try {
            const r = await fetch(b.url, { cache: "no-store", signal: AbortSignal.timeout(5000) });
            if (!r.ok) return null;
            return await r.json();
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
      it.current_high_bid || it.price,
      it.sale_mode === "auction" ? "min_bid" : "cash",
      it.acres,
      it.sale_mode === "auction" ? "auction_open" : "listed",
      it.status === "active" ? 1 : 0,
      it.title,
      it.county || "",
      it.apn || "",
      (it.deadline || "").slice(0, 10),
      1,
    ]);
  } catch {
    return [];
  }
}

function scoreRecommended(r) {
  // Higher = better default ordering: direct > priced+acres+mapped > priced > active
  let s = 0;
  if (r[13]) s += 1000;
  if (r[8]) s += 100;
  if (r[4] != null && r[4] > 0) s += 40;
  if (r[6] != null && r[6] > 0) s += 30;
  if (r[1] != null) s += 15;
  if (r[5] === "cash") s += 10;
  return s;
}

export async function GET(request) {
  try {
    const reqUrl = new URL(request.url);
    const origin = `${reqUrl.protocol}//${reqUrl.host}`;
    const sp = reqUrl.searchParams;

    const state = (sp.get("state") || "").trim().toUpperCase().slice(0, 2);
    const mode = (sp.get("mode") || sp.get("kind") || "").trim().toLowerCase();
    const q = (sp.get("q") || "").trim().toLowerCase();
    const minPrice = sp.get("min_price") ? Number(sp.get("min_price")) : NaN;
    const maxPrice = sp.get("max_price") ? Number(sp.get("max_price")) : NaN;
    const minAcres = sp.get("min_acres") ? Number(sp.get("min_acres")) : NaN;
    const maxAcres = sp.get("max_acres") ? Number(sp.get("max_acres")) : NaN;
    const includeClosed = sp.get("include_closed") === "1";
    const sort = (sp.get("sort") || "recommended").trim().toLowerCase();
    const limit = Math.max(1, Math.min(100, Number(sp.get("limit")) || 25));
    const offset = Math.max(0, Number(sp.get("offset")) || 0);

    const [officialRows, directRows] = await Promise.all([loadOfficialRows(origin), loadDirectRows()]);
    const all = directRows.concat(officialRows);

    const baseFiltered = [];
    const counts = { all: 0, buy_now: 0, auction: 0, offer: 0, direct: 0 };
    const statesSet = new Set();

    for (let i = 0; i < all.length; i++) {
      const r = all[i];
      if (!includeClosed && !r[8]) continue;
      if (state && r[3] !== state) continue;
      if (Number.isFinite(minPrice) && (r[4] == null || r[4] < minPrice)) continue;
      if (Number.isFinite(maxPrice) && (r[4] == null || r[4] > maxPrice)) continue;
      if (Number.isFinite(minAcres) && (!r[6] || r[6] < minAcres)) continue;
      if (Number.isFinite(maxAcres) && (!r[6] || r[6] > maxAcres)) continue;
      if (q && `${r[9]} ${r[10]} ${r[11]} ${r[3]}`.toLowerCase().indexOf(q) < 0) continue;

      counts.all++;
      if (r[5] === "cash") counts.buy_now++;
      if (r[5] === "min_bid" || r[7] === "auction_open" || r[7] === "auction_terms") counts.auction++;
      if (r[5] === "none" && r[7] !== "auction_open" && r[7] !== "auction_terms") counts.offer++;
      if (r[13]) counts.direct++;
      statesSet.add(r[3]);

      if (matchesMode(r, mode)) baseFiltered.push(r);
    }

    baseFiltered.sort((a, b) => {
      if (sort === "price_asc") {
        const av = a[4] != null ? a[4] : 1e15;
        const bv = b[4] != null ? b[4] : 1e15;
        return av - bv;
      }
      if (sort === "price_desc") {
        const av = a[4] != null ? a[4] : -1;
        const bv = b[4] != null ? b[4] : -1;
        return bv - av;
      }
      if (sort === "ppa_asc") {
        const ap = a[4] > 0 && a[6] > 0 ? a[4] / a[6] : 1e15;
        const bp = b[4] > 0 && b[6] > 0 ? b[4] / b[6] : 1e15;
        return ap - bp;
      }
      if (sort === "acres_desc") {
        return (b[6] || 0) - (a[6] || 0);
      }
      if (sort === "deadline") {
        const ad = a[12] || "9999";
        const bd = b[12] || "9999";
        return ad < bd ? -1 : ad > bd ? 1 : 0;
      }
      // recommended
      const diff = scoreRecommended(b) - scoreRecommended(a);
      if (diff !== 0) return diff;
      const ad = a[12] || "9999";
      const bd = b[12] || "9999";
      if (ad !== bd) return ad < bd ? -1 : 1;
      return a[9] < b[9] ? -1 : 1;
    });

    const page = baseFiltered.slice(offset, offset + limit).map((r) => {
      const ppa = r[4] > 0 && r[6] > 0 ? Math.round((r[4] / r[6]) * 100) / 100 : null;
      const isDirect = Boolean(r[13]);
      return {
        id: r[0],
        title: r[9],
        state: r[3],
        county: r[10],
        apn: r[11] || null,
        deal_mode: classifyMode(r),
        is_direct: isDirect,
        price: r[4],
        price_kind: r[5],
        acres: r[6],
        usd_per_acre: ppa,
        status: r[7],
        available: Boolean(r[8]),
        deadline: r[12] || null,
        lat: r[1],
        lon: r[2],
        url: isDirect
          ? `https://landosaur.com/direct/?id=${encodeURIComponent(r[0])}`
          : `https://landosaur.com/land/${r[0]}/`,
        xray_url:
          r[1] != null && r[2] != null
            ? `https://landosaur.com/api/xray/?lat=${r[1]}&lon=${r[2]}`
            : null,
      };
    });

    return jsonResp({
      ok: true,
      total: baseFiltered.length,
      offset,
      limit,
      returned: page.length,
      counts_by_mode: counts,
      states_matching: Array.from(statesSet).sort(),
      results: page,
    });
  } catch (err) {
    console.error("[search GET] error:", err);
    return jsonResp({ error: "Search service temporarily unavailable." }, 502, "no-store");
  }
}
