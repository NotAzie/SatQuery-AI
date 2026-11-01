import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import cesium from "vite-plugin-cesium";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

// The dev server proxies the backend so the browser sees one origin (no CORS, cookies work).
export default defineConfig({
  plugins: [react(), tailwindcss(), cesium()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiProxyTarget, changeOrigin: true, ws: true },
      "/healthz": apiProxyTarget,
      "/readyz": apiProxyTarget,
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts", "tests/**/*.test.ts"] },
});
