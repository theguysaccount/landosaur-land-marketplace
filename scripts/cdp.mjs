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
  const binary = findChrome();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "lando-cdp-"));
  const chrome = spawn(binary, [...(process.env.CI ? ["--no-sandbox"] : []), "--headless=new", "--disable-gpu",
    "--hide-scrollbars", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const exited = new Promise((resolve) => {
    chrome.once("exit", resolve);
    chrome.once("error", resolve);
  });
  let ws;
  let closing;
  function close() {
    closing ??= (async () => {
      ws?.close();
      const force = setTimeout(() => chrome.kill("SIGKILL"), 750);
      chrome.stderr.destroy();
      chrome.kill("SIGTERM");
      try {
        await exited;
      } finally {
        clearTimeout(force);
        await fs.promises.rm(profile, { recursive: true, force: true, maxRetries: 2, retryDelay: 50 });
      }
    })();
    return closing;
  }
  try {
    const wsUrl = await new Promise((resolve, reject) => {
      let buf = "";
      const deadline = setTimeout(() => reject(new Error("Chrome DevTools did not start")), 10000);
      chrome.once("error", reject);
      chrome.once("exit", () => {
        clearTimeout(deadline);
        reject(new Error("Chrome exited: " + buf.slice(-500)));
      });
      chrome.stderr.on("data", (data) => {
        buf = (buf + data).slice(-4096);
        const match = buf.match(/DevTools listening on (ws:\/\/\S+)/);
        if (match) {
          clearTimeout(deadline);
          resolve(match[1]);
        }
      });
    });
    ws = new WebSocket(wsUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", () => reject(new Error("Chrome DevTools WebSocket failed")), { once: true });
    });
    let seq = 0;
    const waiting = new Map();
    const listeners = new Set();
    ws.addEventListener("close", () => {
      for (const { reject } of waiting.values()) reject(new Error("Chrome DevTools WebSocket closed"));
      waiting.clear();
    });
    ws.addEventListener("message", (e) => {
      const m = JSON.parse(e.data);
      if (m.id && waiting.has(m.id)) {
        const { resolve, reject } = waiting.get(m.id);
        waiting.delete(m.id);
        if (m.error) reject(new Error(m.error.message)); else resolve(m.result);
      } else for (const l of listeners) l(m);
    });
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      if (ws.readyState !== WebSocket.OPEN) return reject(new Error("Chrome DevTools WebSocket closed"));
      const id = ++seq;
      waiting.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    const s = (method, params) => send(method, params, sessionId);
    await s("Page.enable");
    await s("Page.setLifecycleEventsEnabled", { enabled: true });
    await s("Runtime.enable");
    await s("Log.enable");
    const errors = [];
    listeners.add((m) => {
      if (m.sessionId !== sessionId) return;
      if (m.method === "Runtime.exceptionThrown") errors.push("exception: " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
      if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push("console.error: " + m.params.args.map((a) => a.value ?? a.description).join(" "));
      if (m.method === "Log.entryAdded" && m.params.entry.level === "error") errors.push("log: " + m.params.entry.text + " " + (m.params.entry.url || ""));
    });
    const page = {
      errors,
      send: s,
      async goto(url) {
        const loaded = new Set();
        let onLoaded;
        function onLifecycle(message) {
          if (message.sessionId === sessionId && message.method === "Page.lifecycleEvent" &&
              message.params.name === "DOMContentLoaded") {
            loaded.add(message.params.loaderId);
            onLoaded?.(message.params.loaderId);
          }
        }
        listeners.add(onLifecycle);
        try {
          const result = await s("Page.navigate", { url });
          if (result.errorText) throw new Error(url + ": " + result.errorText);
          if (!result.loaderId || loaded.has(result.loaderId)) return;
          await new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error(url + ": DOM did not load")), 20000);
            onLoaded = (loader) => {
              if (loader !== result.loaderId) return;
              clearTimeout(timeout);
              resolve();
            };
          });
        } finally {
          listeners.delete(onLifecycle);
        }
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
        await s("Emulation.setUserAgentOverride", { userAgent: mobile ? PHONE_UA : "" });
      },
    };
    return { page, close };
  } catch (error) {
    await close();
    throw error;
  }
}
