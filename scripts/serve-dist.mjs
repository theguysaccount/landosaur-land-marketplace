// Local release checks use the built files and real API handlers with Blob credentials unset.
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { Readable } from "node:stream";
import { GET as archivedParcel, HEAD as archivedParcelHead } from "../api/parcel.js";

delete process.env.BLOB_READ_WRITE_TOKEN;

const root = resolve("dist");
const port = Number(process.argv[2] || 4651);
const mime = {
  ".css": "text/css", ".html": "text/html; charset=utf-8", ".js": "text/javascript",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
  ".csv": "text/csv", ".txt": "text/plain", ".xml": "application/xml",
};

const server = createServer(async (req, res) => {
  try {
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { Allow: "GET, HEAD" }).end();
      return;
    }
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    const api = url.pathname.match(/^\/api\/([a-z-]+)\/?$/)?.[1];
    if (api) {
      let handler;
      try {
        handler = (await import(`../api/${api}.js`)).GET;
      } catch (error) {
        if (error.code !== "ERR_MODULE_NOT_FOUND" || !error.url?.endsWith(`/api/${api}.js`)) throw error;
      }
      if (!handler) {
        res.writeHead(404).end();
        return;
      }
      const response = await handler(new Request(url, { headers: req.headers }));
      res.writeHead(response.status, Object.fromEntries(response.headers));
      if (response.body && req.method !== "HEAD") Readable.fromWeb(response.body).pipe(res);
      else res.end();
      return;
    }
    let file = resolve(root, "." + decodeURIComponent(url.pathname));
    if (file !== root && !file.startsWith(root + sep)) {
      res.writeHead(404).end();
      return;
    }
    let metadata = await stat(file).catch(() => null);
    if (metadata?.isDirectory()) {
      if (!url.pathname.endsWith("/")) {
        res.writeHead(308, { Location: url.pathname + "/" + url.search }).end();
        return;
      }
      file = resolve(file, "index.html");
      metadata = await stat(file).catch(() => null);
    }
    if (!metadata?.isFile()) {
      if (/^\/land\/[a-z0-9-]+\/?$/.test(url.pathname)) {
        if (!url.pathname.endsWith("/")) {
          res.writeHead(308, { Location: url.pathname + "/" + url.search }).end();
          return;
        }
        const request = new Request(url, { headers: req.headers, method: req.method });
        const response = await (req.method === "HEAD" ? archivedParcelHead : archivedParcel)(request);
        res.writeHead(response.status, Object.fromEntries(response.headers));
        if (response.body) Readable.fromWeb(response.body).pipe(res);
        else res.end();
        return;
      }
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { "Content-Type": mime[extname(file)] || "application/octet-stream", "Content-Length": metadata.size });
    if (req.method === "HEAD") res.end();
    else createReadStream(file).pipe(res);
  } catch (error) {
    console.error(error);
    if (!res.headersSent) res.writeHead(500);
    res.end();
  }
});
server.listen(port, "127.0.0.1");
