// Live Arkansas COSL Auction Token Resolver for landosaur.com
// auction.cosl.org rotates its ListingToken every few hours, causing static stored URLs to
// return "Listing Not Found". This endpoint resolves the live active token for a numeric
// CoSLPropertyId and issues a 302 redirect straight to the active official COSL bidding page.

let cache = { at: 0, map: new Map() };
const CACHE_TTL_MS = 10 * 60 * 1000;

async function resolveCoslUrl(propId) {
  const idStr = String(propId || "").replace(/[^0-9]/g, "");
  if (!idStr) return null;
  const now = Date.now();
  if (!cache.map.size || now - cache.at > CACHE_TTL_MS) {
    const fresh = new Map();
    for (let page = 1; page <= 10; page++) {
      const resp = await fetch(
        `https://auction.cosl.org/auctions/grid_read?page=${page}&pageSize=500`,
        {
          headers: {
            "User-Agent":
              "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            Accept: "application/json, text/plain, */*",
          },
          signal: AbortSignal.timeout(9000),
        }
      );
      if (!resp.ok) break;
      const data = await resp.json();
      const rows = Array.isArray(data?.Data) ? data.Data : Array.isArray(data) ? data : [];
      if (!rows.length) break;
      for (const row of rows) {
        const pid = String(row.CoSLPropertyId || "");
        const tok = row.ListingToken || row.EncryptedId || "";
        if (pid && tok) fresh.set(pid, tok);
      }
      if (rows.length < 500) break;
    }
    if (fresh.size) cache = { at: now, map: fresh };
  }
  const token = cache.map.get(idStr);
  return token
    ? `https://auction.cosl.org/Auction/Listing/${encodeURIComponent(token)}`
    : null;
}

export async function GET(request) {
  const url = new URL(request.url);
  const rawId = url.searchParams.get("id") || "";
  const idStr = rawId.replace(/[^0-9]/g, "");
  if (!idStr) {
    return new Response(
      JSON.stringify({ error: "Missing numeric Arkansas COSL parcel id (?id=...)." }),
      {
        status: 400,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-store, max-age=0",
        },
      }
    );
  }
  try {
    const target = await resolveCoslUrl(idStr);
    const dest = target || "https://auction.cosl.org/Auctions/ListingsView";
    return new Response(null, {
      status: 302,
      headers: {
        Location: dest,
        "Cache-Control": "no-store, max-age=0",
        "X-Robots-Tag": "noindex, nofollow",
      },
    });
  } catch (err) {
    console.error("[api/cosl] redirect failed:", err);
    return new Response(null, {
      status: 302,
      headers: {
        Location: "https://auction.cosl.org/Auctions/ListingsView",
        "Cache-Control": "no-store, max-age=0",
        "X-Robots-Tag": "noindex, nofollow",
      },
    });
  }
}
