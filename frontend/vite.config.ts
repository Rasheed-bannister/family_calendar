/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Built output is served by Flask from src/static/app at /static/app/...
// `npm run dev` proxies API calls to the Flask server on :5000.
const BACKEND = process.env.BACKEND_URL || "http://localhost:5000";

export default defineConfig({
  plugins: [svelte()],
  base: "/static/app/",
  resolve: {
    alias: {
      $lib: fileURLToPath(new URL("./src/lib", import.meta.url)),
      $components: fileURLToPath(new URL("./src/components", import.meta.url)),
    },
  },
  build: {
    outDir: "../src/static/app",
    emptyOutDir: true,
    sourcemap: true,
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/api", "/events", "/chores", "/pir", "/health", "/upload", "/google", "/static/photos"].map(
        (path) => [path, { target: BACKEND, changeOrigin: false }],
      ),
    ),
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});
