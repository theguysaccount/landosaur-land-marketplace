import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "../mcp/landosaur-mcp.mjs";
import "../site/geo.js";

const rpc = (method, params = {}) => ({ jsonrpc: "2.0", id: 1, method, params });
const modern = { "io.modelcontextprotocol/protocolVersion": "2026-07-28" };

test("MCP supports legacy initialization and modern discovery", async () => {
  const server = createServer();
  const discovered = await server(rpc("server/discover", { _meta: modern }));
  assert.equal(discovered.result.resultType, "complete");
  assert.equal(discovered.result.supportedVersions[0], "2026-07-28");
  assert.equal((await server(rpc("tools/list", { _meta: modern }))).result.tools.length, 6);
  assert.equal((await server(rpc("initialize", { protocolVersion: "2025-11-25" }))).result.protocolVersion, "2025-11-25");
  assert.equal((await server(rpc("tools/list"))).result.tools.length, 6);
});

test("MCP preview never transmits a write and strips its confirmation field", async () => {
  let calls = 0;
  const server = createServer("https://landosaur.test", async (url, options) => {
    calls++;
    assert.equal(url.pathname, "/api/alerts/");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { state: "KS" });
    return Response.json({ ok: true });
  });
  const call = (args) => server(rpc("tools/call", { name: "create_land_alert", arguments: args, _meta: modern }));
  assert.equal((await call({ state: "KS" })).result.isError, true);
  assert.equal(calls, 0);
  assert.equal((await call({ state: "KS", confirmed: true })).result.content[0].text, '{"ok":true}');
  assert.equal(calls, 1);
});

test("shared polygon predicate includes its edges and matches across the date line", () => {
  const { decode, matcher, measure } = globalThis.LandosaurGeo;
  const points = decode("179,51;-179,51;-179,53;179,53");
  assert.ok(measure(points));
  const matches = matcher(points);
  assert.equal(matches(179.5, 52), true);
  assert.equal(matches(-179.5, 52), true);
  assert.equal(matches(-179, 52), true);
  assert.equal(matches(0, 52), false);
  assert.equal(matches(179.5, null), false);
});
