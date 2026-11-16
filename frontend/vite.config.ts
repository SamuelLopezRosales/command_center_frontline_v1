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
    // Las pruebas de Playwright (tests/e2e) tienen su propio ejecutor.
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Con la máquina cargada (suite completa, otros procesos) 5 s no alcanzan para pantallas grandes.
    testTimeout: 20000,
  },
});
