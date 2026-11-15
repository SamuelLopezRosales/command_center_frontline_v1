import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { CABECERAS_DESARROLLO } from "./cabeceras";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    headers: CABECERAS_DESARROLLO,
    proxy: {
      "/api": { target: process.env.CC_API_URL ?? "http://localhost:8000", changeOrigin: true },
      "/d": { target: process.env.CC_API_URL ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
