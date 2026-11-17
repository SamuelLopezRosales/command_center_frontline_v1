// Genera los tipos de la API desde contracts/openapi/*.json (T-119). Con --verificar falla si
// los tipos del repositorio no coinciden con los contratos.
import openapiTS, { astToString } from "openapi-typescript";
import { readdirSync, readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join, dirname } from "node:path";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..");
const contratos = join(raiz, "..", "contracts", "openapi");
const salida = join(raiz, "src", "api-client", "generado");
const verificar = process.argv.includes("--verificar");
mkdirSync(salida, { recursive: true });
let desactualizados = 0;
for (const f of readdirSync(contratos).filter((x) => x.endsWith(".json"))) {
  const ast = await openapiTS(pathToFileURL(join(contratos, f)));
  // Sin espacios al final de línea y con un solo salto final: así coincide con lo que dejan los
  // hooks de limpieza de pre-commit y la verificación no depende de ellos.
  const texto = ("// Generado por scripts/generar-api.mjs. No editar.\n" + astToString(ast))
    .split("\n")
    .map((linea) => linea.replace(/[ \t]+$/, ""))
    .join("\n")
    .replace(/\n*$/, "\n");
  const destino = join(salida, f.replace(".json", ".ts"));
  if (verificar) {
    if (!existsSync(destino) || readFileSync(destino, "utf8") !== texto) {
      console.error(`Desactualizado: ${f}. Ejecute npm run api:generar`);
      desactualizados++;
    }
  } else writeFileSync(destino, texto);
}
if (verificar && desactualizados) process.exit(1);
