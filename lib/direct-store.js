import { get, put } from "@vercel/blob";

export const LISTING_PREFIX = "direct/listings/";
export const OFFER_PREFIX = "direct/offers/";

export async function readDirect(path) {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return null;
  const blob = await get(path, { access: "public", useCache: false });
  return blob?.statusCode === 200 ?
    { value: await new Response(blob.stream).json(), etag: blob.blob.etag } : null;
}

export function writeDirect(path, value, etag) {
  return put(path, JSON.stringify(value, null, 2), {
    access: "public", contentType: "application/json", addRandomSuffix: false,
    ...(etag ? { ifMatch: etag } : { allowOverwrite: false }),
  });
}

export function checkoutUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

export function bidStats(entries) {
  const bids = (entries || []).filter((entry) => entry.action === "bid");
  return { bid_count: bids.length, current_high_bid: bids.length ? Math.max(...bids.map((entry) => entry.amount)) : null };
}
