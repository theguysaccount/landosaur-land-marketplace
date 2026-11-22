// Minimal Chrome DevTools Protocol driver for the end-to-end test and screenshots. Needs Node 22+ (global WebSocket).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

export const PHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

function findChrome() {
  const c = [process.env.CHROME, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium-browser", "/usr/bin/chromium"];
  for (const p of c) if (p && fs.existsSync(p)) return p;
  throw new Error("Chrome not found; set CHROME");
}

export async function launch() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "lando-cdp-"));
  const chrome = spawn(findChrome(), [...(process.env.CI ? ["--no-sandbox"] : []), "--headless=new", "--disable-gpu",
    "--hide-scrollbars", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = "";
    chrome.stderr.on("data", (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) resolve(m[1]); });
    chrome.on("exit", () => reject(new Error("Chrome exited: " + buf.slice(-500))));
  });
  const ws = new WebSocket(wsUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let seq = 0;
  const waiting = new Map();
  const listeners = new Set();
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) {
      const { resolve, reject } = waiting.get(m.id);
      waiting.delete(m.id);
      if (m.error) reject(new Error(m.error.message)); else resolve(m.result);
    } else for (const l of listeners) l(m);
  });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++seq;
    waiting.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  const s = (method, params) => send(method, params, sessionId);
  await s("Page.enable");
  await s("Runtime.enable");
  await s("Log.enable");
  const errors = [];
  listeners.add((m) => {
    if (m.sessionId !== sessionId) return;
    if (m.method === "Runtime.exceptionThrown") errors.push("exception: " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push("console.error: " + m.params.args.map((a) => a.value ?? a.description).join(" "));
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error") errors.push("log: " + m.params.entry.text + " " + (m.params.entry.url || ""));
  });
  const once = (method) => new Promise((resolve) => {
    const l = (m) => { if (m.method === method && m.sessionId === sessionId) { listeners.delete(l); resolve(m.params); } };
    listeners.add(l);
  });
  const page = {
    errors,
    send: s,
    async goto(url) {
      const loaded = once("Page.loadEventFired");
      await s("Page.navigate", { url });
      await loaded;
      await new Promise((r) => setTimeout(r, 400));
    },
    async eval(expression) {
      const r = await s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error("eval failed: " + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
      return r.result.value;
    },
    async waitFor(expression, ms = 8000) {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        if (await page.eval(expression)) return true;
        await new Promise((r) => setTimeout(r, 150));
      }
      throw new Error("timed out waiting for " + expression);
    },
    async viewport(width, height, mobile) {
      await s("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
      if (mobile) await s("Emulation.setUserAgentOverride", { userAgent: PHONE_UA });
    },
    once,
  };
  const close = async () => {
    ws.close();
    const exited = new Promise((r) => chrome.once("exit", r));
    chrome.kill();
    await exited;
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  };
  return { page, close };
}
