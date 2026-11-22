// Screenshots of the key pages at desktop (1280px) and phone (390px) widths into docs/screens/.
//   node scripts/screens.mjs https://theguysaccount.github.io/landosaur-land-marketplace
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launch } from "./cdp.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "docs", "screens");
const base = (process.argv[2] || "http://localhost:4651/landosaur-land-marketplace").replace(/\/$/, "");
const pages = [["home", "/"], ["listing", "/land/stl-00209030000/"], ["state", "/land-for-sale/arkansas/"], ["new", "/new/"],
  ["closing", "/closing-soon/"], ["sources", "/sources/"]];
fs.mkdirSync(OUT, { recursive: true });
const { page, close } = await launch();
try {
  for (const [label, width, height, mobile] of [["desktop", 1280, 1400, false], ["phone", 390, 1400, true]]) {
    await page.viewport(width, height, mobile);
    for (const [name, p] of pages) {
      await page.goto(base + p);
      await new Promise((r) => setTimeout(r, 2500));
      const { data } = await page.send("Page.captureScreenshot", { format: "png" });
      fs.writeFileSync(path.join(OUT, `${name}-${label}.png`), Buffer.from(data, "base64"));
      console.log("saved", `docs/screens/${name}-${label}.png`);
    }
  }
} finally {
  await close();
}
