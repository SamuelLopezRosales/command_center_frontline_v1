// Pruebas de extremo a extremo (T-133) contra el stack local ya levantado
// (`.\scripts\local.ps1 up`: SPA en http://localhost:5173, pasarela en 127.0.0.1:8000).
//
// - No se descargan navegadores: se usa el Microsoft Edge de Windows (`channel: "msedge"`).
//   Con CC_E2E_NAVEGADOR=chrome se usa Google Chrome.
// - Un solo worker y sin paralelismo: el stack es compartido y con estado.
// - Traza y captura solo cuando una prueba falla.
import { defineConfig } from "@playwright/test";

export const URL_SPA = process.env.CC_E2E_URL ?? "http://localhost:5173";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts/,
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: "./test-results",
  use: {
    baseURL: URL_SPA,
    channel: process.env.CC_E2E_NAVEGADOR ?? "msedge",
    headless: true,
    viewport: { width: 1440, height: 900 },
    locale: "es-MX",
    timezoneId: "America/Mexico_City",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
});
