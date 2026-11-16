// Contratos (T-132): si un OpenAPI de `contracts/openapi/` cambia sin regenerar el cliente, falla.
//
// Para corregirlo: `npm run api:generar` (en `frontend/`) y confirmar los `.ts` de
// `src/api-client/generado/` junto con el contrato.
//
// Los tipos que usan las funciones `api.ts` de cada feature se importan de `generado/*` con
// `components["schemas"]["..."]`: si un esquema desaparece del contrato, `npm run typecheck`
// (`tsc --noEmit`, también parte de `npm run build`) falla. No se duplica esa comprobación aquí.
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const contratos = join(raiz, "..", "contracts", "openapi");
const generado = join(raiz, "src", "api-client", "generado");

describe("contratos OpenAPI y cliente generado", () => {
  it("cada contrato tiene su cliente generado y no sobran clientes", () => {
    const deContratos = readdirSync(contratos).filter((f) => f.endsWith(".json")).map((f) => f.replace(".json", ""));
    const deClientes = readdirSync(generado).filter((f) => f.endsWith(".ts")).map((f) => f.replace(".ts", ""));
    expect(deContratos.length).toBeGreaterThan(0);
    for (const c of deContratos) expect(existsSync(join(generado, `${c}.ts`)), `falta el cliente de ${c}.json: ejecute npm run api:generar`).toBe(true);
    expect(deClientes.sort()).toEqual(deContratos.sort());
  });

  it("el cliente generado coincide con los contratos (npm run api:verificar)", () => {
    try {
      execFileSync(process.execPath, [join(raiz, "scripts", "generar-api.mjs"), "--verificar"], { cwd: raiz, encoding: "utf8", stdio: "pipe" });
    } catch (e) {
      const salida = e as { stderr?: string; stdout?: string };
      throw new Error(`El cliente de la API está desactualizado. Ejecute «npm run api:generar» en frontend/.\n${salida.stderr ?? ""}${salida.stdout ?? ""}`);
    }
  }, 120_000);
});
