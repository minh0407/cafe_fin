import path from "node:path";
import { fileURLToPath } from "node:url";
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export default {
  root: repository,
  cacheDir: path.join(repository, "frontend/node_modules/.vite/contracts"),
  esbuild: { jsx: "automatic" },
  resolve: { alias: {
    react: path.join(repository, "frontend/node_modules/react"),
    "react-dom": path.join(repository, "frontend/node_modules/react-dom"),
    antd: path.join(repository, "frontend/node_modules/antd"),
  } },
  optimizeDeps: { entries: ["tests/contracts/browser-main.tsx"] },
  server: { host: "127.0.0.1", port: 1422, strictPort: true },
};
