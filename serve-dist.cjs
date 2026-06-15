const http = require("http");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "dist");
const port = Number(process.env.PORT || 4173);

const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp"
};

http
  .createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    const filePath = urlPath === "/" ? "/index.html" : urlPath;
    const resolved = path.resolve(root, `.${filePath}`);
    if (!resolved.startsWith(root)) {
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    const target = fs.existsSync(resolved) && fs.statSync(resolved).isFile()
      ? resolved
      : path.join(root, "index.html");

    fs.readFile(target, (error, data) => {
      if (error) {
        res.writeHead(404);
        res.end("Not found");
        return;
      }
      res.writeHead(200, { "Content-Type": types[path.extname(target)] || "application/octet-stream" });
      res.end(data);
    });
  })
  .listen(port, "0.0.0.0", () => {
    console.log(`Signal static server at http://127.0.0.1:${port}/`);
  });
