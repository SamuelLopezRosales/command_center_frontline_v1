// Revisión automática de accesibilidad con axe-core (T-132, CC-NFR-012).
// Se usa axe-core directamente (sin envoltorio) para no depender de la compatibilidad de
// `vitest-axe` con Vitest 5.
import axe from "axe-core";
import { expect } from "vitest";

/**
 * Reglas desactivadas y motivo:
 * - `color-contrast`: jsdom no calcula estilos ni layout, el resultado no es fiable. El contraste
 *   se revisa en la revisión visual con navegador real (docs/revision_visual_spa.md).
 * - `region`: obliga a que todo el contenido esté en una zona (landmark); al renderizar una pantalla
 *   aislada, sin el `Shell`, siempre falla y es de impacto moderado.
 * - `scrollable-region-focusable`: depende de medidas de layout que jsdom no tiene.
 */
export const REGLAS_DESACTIVADAS = ["color-contrast", "region", "scrollable-region-focusable"];

const IMPACTOS_BLOQUEANTES = ["critical", "serious"];

export async function violacionesGraves(contenedor: Element): Promise<axe.Result[]> {
  const reglas: Record<string, { enabled: boolean }> = {};
  for (const r of REGLAS_DESACTIVADAS) reglas[r] = { enabled: false };
  const resultado = await axe.run(contenedor, { rules: reglas, resultTypes: ["violations"] });
  return resultado.violations.filter((v) => IMPACTOS_BLOQUEANTES.includes(v.impact ?? ""));
}

function describir(v: axe.Result): string {
  const nodos = v.nodes.map((n) => `    - ${n.target.join(" ")}\n      ${n.html.slice(0, 140)}`).join("\n");
  return `[${v.impact}] ${v.id}: ${v.help}\n${nodos}`;
}

/** Falla con la lista legible de violaciones críticas o serias, si las hay. */
export async function esperarAccesible(contenedor: Element) {
  const graves = await violacionesGraves(contenedor);
  expect(graves.map(describir).join("\n"), "violaciones de accesibilidad críticas o serias").toBe("");
}
