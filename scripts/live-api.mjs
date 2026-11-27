// Read-only smoke checks against production. Creates no listings, offers, orders, or alerts.
const base = process.argv[2] || "https://landosaur.com";
const checks = [
  ["/api/search/?limit=1", 200, (body) => body.ok && body.total > 0 && body.results.length === 1],
  ["/api/listings/", 200, (body) => body.storage_configured && Array.isArray(body.listings)],
  ["/api/offers/", 400, (body) => typeof body.error === "string"],
  ["/api/concierge/", 200, (body) => body.ok && body.storage_configured && body.stripe_checkout_configured &&
      body.initiation_fee_usd === 20 && body.concierge_fee_pct === 10],
  ["/api/alerts/", 200, (body) => body.ok && body.storage_configured],
  ["/api/xray/?lat=35.42&lon=-92.45", 200, (body) => body.usgs?.elevation_ft > 0 && body.county?.fips],
  ["/data/atlas.json", 200, (body) => body.states.length === 50 && body.counties.length > 3000],
  ["/.well-known/landosaur-agent.json", 200, (body) => Array.isArray(body.endpoints) || typeof body.endpoints === "object"],
];
const results = await Promise.allSettled(checks.map(async ([path, status, validate]) => {
  const response = await fetch(new URL(path, base), {
    headers: { "Cache-Control": "no-cache" }, signal: AbortSignal.timeout(30000),
  });
  if (response.status !== status || !validate(await response.json())) {
    throw new Error(path + " failed its HTTP or response check (" + response.status + ")");
  }
  if (path.startsWith("/api/") && !response.headers.get("cache-control")?.includes("no-store")) {
    throw new Error(path + " is missing Cache-Control: no-store");
  }
  console.log(status, path);
}));
for (const result of results) {
  if (result.status === "rejected") {
    console.error(result.reason.message);
    process.exitCode = 1;
  }
}
