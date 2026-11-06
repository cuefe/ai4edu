import { createReadStream, existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/** pdf.js 显示中文 PDF 要用的字符映射表和标准字体：开发时直接读，打包时拷到 /pdfjs/ 下。 */
function pdfjsAssets(): Plugin {
  const root = fileURLToPath(new URL("./node_modules/pdfjs-dist", import.meta.url));
  const dirs = ["cmaps", "standard_fonts"];
  return {
    name: "pdfjs-assets",
    configureServer(server) {
      for (const dir of dirs) {
        server.middlewares.use(`/pdfjs/${dir}/`, (req, res, next) => {
          const file = join(root, dir, basename((req.url ?? "").split("?")[0]));
          if (!existsSync(file)) return next();
          res.setHeader("Content-Type", "application/octet-stream");
          createReadStream(file).pipe(res);
        });
      }
    },
    generateBundle() {
      for (const dir of dirs) {
        for (const name of readdirSync(join(root, dir))) {
          this.emitFile({ type: "asset", fileName: `pdfjs/${dir}/${name}`, source: readFileSync(join(root, dir, name)) });
        }
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
