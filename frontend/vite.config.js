import { createReadStream, existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const root = path.dirname(fileURLToPath(import.meta.url));
const imgDir = path.join(root, "img");
const types = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
};

function serveImg() {
  return {
    name: "serve-img",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url || "";
        // Vite 會把 <img src> 編成 /img/xxx?import，這時要交回 Vite，不能直接回圖片位元組。
        if (url.includes("?")) return next();
        const raw = decodeURIComponent(url.split("?")[0]);
        if (!raw.startsWith("/img/")) return next();
        const file = path.resolve(imgDir, raw.slice(5));
        const rel = path.relative(imgDir, file);
        if (rel.startsWith("..") || path.isAbsolute(rel)) return next();
        if (!existsSync(file) || !statSync(file).isFile()) return next();
        res.setHeader("Content-Type", types[path.extname(file).toLowerCase()] || "application/octet-stream");
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  root,
  plugins: [vue(), serveImg()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
