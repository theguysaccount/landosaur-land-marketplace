import { createHash } from "node:crypto";
import { gunzipSync } from "node:zlib";

const PRODUCTION = "https://landosaur.com";
const NO_INDEX = { "X-Robots-Tag": "noindex, follow" };

async function archivedParcel(request, head) {
  const incoming = new URL(request.url);
  const pathSlug = incoming.pathname.match(/^\/land\/([a-z0-9-]+)\/?$/)?.[1];
  const slug = pathSlug || incoming.searchParams.get("parcel") || "";
  const missing = () => new Response(head ? null : "Parcel not found.", { status: 404, headers: NO_INDEX });
  if (!/^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$/.test(slug)) return missing();

  const origin = !process.env.VERCEL && incoming.hostname === "127.0.0.1" ? incoming.origin : PRODUCTION;
  const bucket = createHash("sha256").update(slug).digest("hex").slice(0, 2);
  const source = new URL(`/data/archived-parcels/${bucket}.json`, origin);
  if (process.env.VERCEL_DEPLOYMENT_ID) source.searchParams.set("v", process.env.VERCEL_DEPLOYMENT_ID);
  try {
    const response = await fetch(source, { signal: AbortSignal.timeout(5000), redirect: "error" });
    if (response.status === 404) return missing();
    if (!response.ok) throw new Error(`Archive fetch returned ${response.status}`);
    const pages = await response.json();
    if (!Object.hasOwn(pages, slug)) return missing();
    const document = head ? null : gunzipSync(Buffer.from(pages[slug], "base64"), { maxOutputLength: 1024 * 1024 });
    return new Response(document, { headers: {
      ...NO_INDEX,
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
      "X-Content-Type-Options": "nosniff",
    } });
  } catch (error) {
    console.error("Unable to load archived parcel", error.message);
    return new Response(head ? null : "Parcel archive temporarily unavailable.", {
      status: 503, headers: { ...NO_INDEX, "Cache-Control": "no-store" },
    });
  }
}

export const GET = (request) => archivedParcel(request, false);
export const HEAD = (request) => archivedParcel(request, true);
