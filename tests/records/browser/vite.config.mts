import { defineConfig } from "../../../frontend/node_modules/vite/dist/node/index.js";
import react from "../../../frontend/node_modules/@vitejs/plugin-react/dist/index.js";
import path from "node:path";
import { fileURLToPath } from "node:url";
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
export default defineConfig({
  root: path.join(repo, "frontend"),
  plugins: [react(), { name: "records-test-host", configureServer(server) {
    server.middlewares.use(async (request, response, next) => {
      if (request.url?.split("?")[0] !== "/records-test") return next();
      const harness = `/@fs/${path.join(repo, "tests/records/browser/harness.tsx").replaceAll("\\", "/")}`;
      const html = await server.transformIndexHtml("/records-test", `<html lang="vi"><head><title>Records real API verification</title></head><body><div id="root"></div><script type="module" src="${harness}"></script></body></html>`);
      response.setHeader("Content-Type", "text/html; charset=utf-8");
      response.end(html);
    });
  } }],
  server: { host: "127.0.0.1", port: 80, strictPort: true, hmr: false, allowedHosts: ["tauri.localhost"], fs: { allow: [repo] } },
  resolve: { alias: Object.fromEntries(["react", "react-dom", "@tanstack/react-query", "antd"].map((name) => [name, path.join(repo, "frontend/node_modules", name)])), dedupe: ["react", "react-dom"] },
});
