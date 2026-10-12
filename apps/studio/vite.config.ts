/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// `npm run dev` proxies the API to a running `nw studio --no-open` (port NEUROWEAVE_PORT, default
// 8765). `npm run build` writes into the Python package so `nw studio` can serve it.
export default defineConfig(({ mode }) => {
  const port = loadEnv(mode, ".", "").NEUROWEAVE_PORT || "8765";
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: { "/api": `http://127.0.0.1:${port}` },
    },
    build: {
      outDir: "../../src/neuroweave/server/static",
      emptyOutDir: true,
      chunkSizeWarningLimit: 900,
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.ts"],
    },
  };
});
