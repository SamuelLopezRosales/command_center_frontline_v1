// Toma las capturas de la revisión visual (T-134) contra el stack local: `npm run e2e:capturas`.
import { spawnSync } from "node:child_process";

const r = spawnSync("npx", ["playwright", "test", "tests/e2e/09_capturas.spec.ts"], {
  stdio: "inherit",
  shell: true,
  env: { ...process.env, CC_E2E_CAPTURAS: "1" },
});
process.exit(r.status ?? 1);
