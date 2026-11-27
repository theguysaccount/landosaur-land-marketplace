// Render generated share-card HTML with one task-scoped headless Chrome process.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { launch } from "./cdp.mjs";

const [source, output] = process.argv.slice(2).map((dir) => path.resolve(dir));
const names = (await fs.readdir(source)).filter((name) => name.endsWith(".html")).sort();
if (!names.length) throw new Error("No rendered share-card templates in " + source);
await fs.mkdir(output, { recursive: true });
const { page, close } = await launch();
try {
  await page.viewport(1200, 630, false);
  for (const name of names) {
    await page.goto(pathToFileURL(path.join(source, name)).href);
    if (!(await page.eval("!!document.querySelector('h1')"))) throw new Error("Empty share card " + name);
    const { data } = await page.send("Page.captureScreenshot", { format: "png" });
    await fs.writeFile(path.join(output, name.replace(/\.html$/, ".png")), Buffer.from(data, "base64"));
  }
} finally {
  await close();
}
console.log(`Share images: ${names.length} rendered into ${output}`);
