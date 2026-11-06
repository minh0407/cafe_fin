import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
export default {
  cacheDir: path.join(root, "frontend/node_modules/.vite-reporting-qa"),
  root: path.join(root, "tests/reporting/ui"),
  server: {
    host: "127.0.0.1",
    port: 1431,
    strictPort: true,
    fs: { allow: [root] },
  },
  resolve: {
    alias: {
      react: path.join(root, "frontend/node_modules/react"),
      "react-dom": path.join(root, "frontend/node_modules/react-dom"),
      antd: path.join(root, "frontend/node_modules/antd"),
    },
  },
  esbuild: { jsx: "automatic" },
};
