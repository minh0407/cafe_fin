// Bundle the actual records entry even while the coordinator registry contains a stub.
import { build } from "../../../frontend/node_modules/vite/dist/node/index.js";
import react from "../../../frontend/node_modules/@vitejs/plugin-react/dist/index.js";
import path from "node:path";
import os from "node:os";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const outDir = path.join(os.tmpdir(), `cafe-fin-records-feature-build-${randomUUID()}`);
await build({
  configFile: false,
  root: path.join(repo, "frontend"),
  plugins: [react()],
  build: {
    outDir,
    emptyOutDir: false,
    lib: { entry: path.join(repo, "frontend/src/features/records/index.ts"), formats: ["es"], fileName: "records" },
    rollupOptions: { external: ["react", "react-dom", "react/jsx-runtime", "antd", "@tanstack/react-query", "zustand", "@tauri-apps/api/core"] },
  },
});
console.log("Records feature output:", outDir);
