// Desktop and 375px mobile screenshots in both themes.
// Usage: node scripts/screens.mjs https://landosaur.com /absolute/output-dir [route ...]
import fs from "node:fs/promises";
import path from "node:path";
import { launch } from "./cdp.mjs";

const base = (process.argv[2] || "http://127.0.0.1:4651").replace(/\/$/, "");
const out = path.resolve(process.argv[3] || "docs/screens");
const defaults = ["/", "/deals/", "/tax-sales/", "/land-atlas/", "/services/", "/xray/", "/land/ks-snco-0973604015014000/"];
const routes = process.argv.length > 4 ? process.argv.slice(4) : defaults;
const ready = {
  "/": "/listings match/.test(document.querySelector('#map-count')?.textContent)",
  "/tax-sales/": "document.querySelector('#tax-cartogram .us-tile')",
  "/land-atlas/": "document.querySelector('#atlas-cartogram .us-tile')",
};
await fs.mkdir(out, { recursive: true });
const { page, close } = await launch();
try {
  for (const [device, width, height, mobile] of [["desktop", 1440, 1000, false], ["mobile", 375, 812, true]]) {
    await page.viewport(width, height, mobile);
    for (const theme of ["light", "dark"]) {
      await page.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
      for (const route of routes) {
        await page.goto(base + route);
        const url = new URL(route, base);
        if (ready[url.pathname]) await page.waitFor(ready[url.pathname], 15000);
        if (/^#[a-z][a-z0-9-]*$/i.test(url.hash)) {
          await page.eval(`document.getElementById(${JSON.stringify(url.hash.slice(1))})?.scrollIntoView({ behavior: "instant", block: "start" })`);
        }
        await page.eval(`Promise.race([
          document.fonts.ready,
          new Promise((resolve) => setTimeout(resolve, 1200))
        ]).then(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))`);
        if (!(await page.eval("!!document.querySelector('#main h1') && !document.querySelector('[name=robots]')?.content.startsWith('noindex,nofollow')"))) {
          throw new Error("Unexpected screenshot page at " + route);
        }
        const name = [url.pathname, /^#[a-z][a-z0-9-]*$/i.test(url.hash) ? url.hash.slice(1) : ""]
          .join("/").split("/").filter(Boolean).join("-") || "home";
        const { data } = await page.send("Page.captureScreenshot", { format: "png" });
        await fs.writeFile(path.join(out, `${name}-${device}-${theme}.png`), Buffer.from(data, "base64"));
      }
    }
  }
} finally {
  await close();
}
console.log(`Saved ${routes.length * 4} screenshots in ${out}`);
