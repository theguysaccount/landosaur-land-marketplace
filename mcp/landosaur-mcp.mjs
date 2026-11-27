#!/usr/bin/env node
import { readFileSync, realpathSync } from "node:fs";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const spec = JSON.parse(readFileSync(new URL("./openapi.json", import.meta.url), "utf8"));
const current = "2026-07-28";
const legacy = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const serverInfo = { name: "landosaur-mcp", version: spec.info.version };
const capabilities = { tools: {} };
const instructions = "Show users the official agency or seller URL and explain when values represent bids or benchmarks. Confirm with the user before filing an order, creating an alert, or publishing a listing.";
const confirmation = { type: "boolean", const: true, description: "Set true only after the user approves the exact submitted details." };

function endpointInput(path, method) {
  const operation = spec.paths[path][method];
  if (method === "get") return {
    type: "object", properties: Object.fromEntries((operation.parameters || []).map((p) => [p.name, p.schema])),
    additionalProperties: false,
  };
  const name = operation.requestBody.content["application/json"].schema.$ref.split("/").at(-1);
  const schema = spec.components.schemas[name];
  return { ...schema, properties: { ...schema.properties, confirmed: confirmation },
    required: [...(schema.required || []), "confirmed"], additionalProperties: false };
}

const definitions = [
  ["search_land", "/api/search/", "get", "Search active public-agency and direct parcels by price, acreage, state, keyword, or drawn polygon."],
  ["parcel_xray", "/api/xray/", "get", "Check federal parcel data by coordinates or U.S. place, including electric utility and county benchmarks."],
  ["get_land_atlas", "/data/atlas.json", "get", "Get Landosaur's national and state benchmarks and inventory counts, optionally filtered by two-letter state."],
  ["create_land_alert", "/api/alerts/", "post", "Save an approved search and get live JSON and Atom feed URLs."],
  ["publish_land_listing", "/api/listings/", "post", "Publish a real seller-authorized direct listing. Save the returned private edit token."],
  ["hire_land_agent", "/api/concierge/", "post", "Open the user's approved Land Agent dossier and return the separate $20 checkout link and tracking code."],
].map(([name, path, method, description]) => ({
  path, method,
  tool: { name, description,
    inputSchema: name === "get_land_atlas" ? {
      type: "object", properties: { state: { type: "string", pattern: "^[A-Z]{2}$" }, include_counties: { type: "boolean" } }, additionalProperties: false,
    } : endpointInput(path, method),
    annotations: { readOnlyHint: method === "get", destructiveHint: false, idempotentHint: method === "get", openWorldHint: true },
  },
}));

function toolResult(value, isError = false) {
  return { content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value) }], ...(isError ? { isError: true } : {}) };
}

export function createServer(base = spec.servers[0].url, request = fetch) {
  let initialized = false;
  async function call(params) {
    const definition = definitions.find(({ tool }) => tool.name === params?.name);
    if (!definition) return toolResult("Unknown Landosaur tool.", true);
    const args = params.arguments ?? {};
    if (!args || typeof args !== "object" || Array.isArray(args)) return toolResult("Provide an object of tool arguments.", true);
    const { path, method, tool } = definition;
    const { properties, required = [] } = tool.inputSchema;
    if (method === "post" && args.confirmed !== true) return toolResult("Ask the user to confirm the exact request before submitting.", true);
    if (Object.keys(args).some((key) => !Object.hasOwn(properties, key)) ||
        required.some((key) => args[key] == null || args[key] === "")) {
      return toolResult("Check the required and allowed fields in the tool schema.", true);
    }

    const url = new URL(path, base);
    const options = { method: method.toUpperCase(), signal: AbortSignal.timeout(35000), redirect: "error" };
    if (method === "post") {
      const { confirmed, ...payload } = args;
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(payload);
    } else if (path.startsWith("/api/")) {
      for (const [key, value] of Object.entries(args)) if (value != null) url.searchParams.set(key, String(value));
    }
    try {
      const response = await request(url, options);
      const data = await response.json();
      if (!response.ok) return toolResult(data.error || "Landosaur HTTP " + response.status, true);
      if (path === "/data/atlas.json") {
        const state = args.state ? String(args.state).toUpperCase() : "";
        const { counties, states, ...national } = data;
        const selected = state ? states.filter((s) => s.code === state) : states;
        if (!selected.length) return toolResult("No Atlas entry for that state code.", true);
        return toolResult({
          ...national, states: selected, county_count: counties.length,
          ...(state && args.include_counties ? { counties: counties.filter((row) => row[2] === state) } : {}),
          source: url.href,
        });
      }
      return toolResult(data);
    } catch {
      return toolResult("The Landosaur API could not be reached or returned invalid JSON.", true);
    }
  }

  return async function dispatch(message) {
    const id = message?.id;
    const rpc = { jsonrpc: "2.0", ...(id == null ? {} : { id }) };
    const error = (code, message, data) => ({ ...rpc, error: { code, message, ...(data ? { data } : {}) } });
    if (message?.jsonrpc !== "2.0" || typeof message.method !== "string" ||
        ("id" in message && typeof id !== "string" && !Number.isInteger(id))) return error(-32600, "Invalid Request");
    if (id == null) return;
    const { method, params } = message;
    const metaVersion = params?._meta?.["io.modelcontextprotocol/protocolVersion"];
    if (metaVersion && metaVersion !== current) {
      return error(-32022, "Unsupported protocol version", { supported: [current, ...legacy], requested: metaVersion });
    }
    const meta = { "io.modelcontextprotocol/serverInfo": serverInfo };
    const success = (result) => ({ ...rpc, result: metaVersion ? { resultType: "complete", ...result, _meta: meta } : result });
    if (method === "server/discover") return { ...rpc, result: {
      resultType: "complete", supportedVersions: [current, ...legacy], capabilities, instructions, _meta: meta,
    } };
    if (method === "initialize") {
      initialized = true;
      return success({ protocolVersion: legacy.includes(params?.protocolVersion) ? params.protocolVersion : legacy[0], capabilities, serverInfo, instructions });
    }
    if (method === "ping") return success({});
    if (!initialized && !metaVersion) return error(-32600, "Initialize or provide modern request metadata.");
    if (method === "tools/list") return success({ tools: definitions.map(({ tool }) => tool) });
    if (method === "tools/call") return success(await call(params));
    return error(-32601, "Method not found");
  };
}

async function run() {
  const dispatch = createServer();
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const pending = new Set();
  function reply(data) { if (data) process.stdout.write(JSON.stringify(data) + "\n"); }
  for await (const line of input) {
    if (!line.trim()) continue;
    let message;
    try { message = JSON.parse(line); }
    catch { reply({ jsonrpc: "2.0", error: { code: -32700, message: "Parse error" } }); continue; }
    const task = dispatch(message).then(reply).catch(() => reply({
      jsonrpc: "2.0", id: message?.id, error: { code: -32603, message: "Internal error" },
    }));
    pending.add(task);
    task.finally(() => pending.delete(task));
  }
  await Promise.allSettled(pending);
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) await run();
