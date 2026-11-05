import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
// God's Eye exposes these server/build integrations as JavaScript without .d.ts files.
// @ts-expect-error Vendored JavaScript integration; its runtime contract is exercised by the build.
import { resolveAllowedHosts } from "../earth-view/build/allowedHosts.js";
// @ts-expect-error Vendored JavaScript integration; its runtime contract is exercised by the build.
import { createBrowserViteConfig } from "../earth-view/build/vite.js";
// @ts-expect-error Vendored JavaScript integration; its runtime contract is exercised by the build.
import { localMcpPlugin } from "../earth-view/server/mcp/plugin.js";
// @ts-expect-error Vendored JavaScript integration; its runtime contract is exercised by the build.
import { apiNotFoundPlugin } from "../earth-view/server/standalone/api-not-found.js";
// @ts-expect-error Vendored JavaScript integration; its runtime contract is exercised by the build.
import { standaloneVoiceTools } from "../earth-view/server/standalone/voiceTools.js";
// @ts-expect-error Vendored JavaScript integration; its runtime contract is exercised by the build.
import { localProviderPlugins } from "../earth-view/server/providers/local.js";

const repositoryRoot = fileURLToPath(new URL("../../", import.meta.url));
const earthRoot = fileURLToPath(new URL("../earth-view", import.meta.url));
const publicDir = fileURLToPath(new URL("../earth-view/public", import.meta.url));

// Keep God's Eye's provider services and full template pipeline while using
// the Platform API as the only `/api/v1` backend.
export default defineConfig(({ command, mode }) => {
  const loaded = {
    ...loadEnv(mode, earthRoot, ""),
    ...loadEnv(mode, repositoryRoot, ""),
  };
  for (const [key, value] of Object.entries(loaded)) {
    if (process.env[key] === undefined) process.env[key] = value;
  }
  const apiProxyTarget =
    process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
  const platformProxy = {
    "/api": { target: apiProxyTarget, changeOrigin: true, ws: true },
    "/healthz": apiProxyTarget,
    "/readyz": apiProxyTarget,
  };

  const browser = createBrowserViteConfig({
    plugins: [
      react(),
      tailwindcss(),
      ...localProviderPlugins({
        realtime: { tools: standaloneVoiceTools() },
        keySetupSourceRoot: earthRoot,
        keySetupEnvFile: fileURLToPath(new URL("../../.env", import.meta.url)),
      }),
      localMcpPlugin(),
      apiNotFoundPlugin(),
    ],
    publicDir,
    googleApiKey: process.env.GOOGLE_MAPS_API_KEY,
    cesiumToken: process.env.CESIUM_ION_TOKEN || process.env.VITE_CESIUM_ION_TOKEN,
    host: process.env.HOST ?? "localhost",
    port: process.env.PORT ?? "5173",
    allowedHosts: resolveAllowedHosts(process.env.GEV_ALLOWED_HOSTS),
    command,
  });

  return {
    ...browser,
    // God’s Eye dependencies are installed and resolved from earthRoot. The
    // standalone config’s forced dependency prebundle resolves from this Vite
    // root instead, producing missing-package errors in the integrated app.
    optimizeDeps: { ...browser.optimizeDeps, include: [] },
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
      dedupe: ["cesium"],
    },
    server: {
      ...browser.server,
      // The Earth runtime's CSP blocks Vite React's inline Fast Refresh preamble.
      hmr: false,
      fs: {
        ...browser.server?.fs,
        allow: [fileURLToPath(new URL(".", import.meta.url)), earthRoot],
      },
      proxy: platformProxy,
    },
    preview: {
      ...browser.preview,
      proxy: platformProxy,
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    },
  };
});
