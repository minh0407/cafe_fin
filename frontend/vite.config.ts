import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  define: { __CAFE_FIN_BROWSER_PREVIEW__: JSON.stringify(process.env.VITE_CAFE_FIN_BROWSER_PREVIEW === "1") },
  clearScreen: false,
  server: { host: "127.0.0.1", port: 1420, strictPort: true },
});
