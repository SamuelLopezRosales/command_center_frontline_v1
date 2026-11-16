// Comprueba si el stack local responde. Si no, las pruebas se saltan con un mensaje claro
// (ver `base.ts`): no se levanta nada aquí para no tocar un stack compartido.
export default async function globalSetup() {
  const spa = process.env.CC_E2E_URL ?? "http://localhost:5173";
  const fallas: string[] = [];
  for (const [nombre, url] of [
    ["SPA", spa],
    // La pasarela se alcanza a través del proxy de Vite (sin credenciales: cualquier respuesta HTTP sirve).
    ["pasarela", `${spa}/api/v1/usuarios/yo`],
  ] as const) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(5000) });
      if (r.status >= 500) fallas.push(`${nombre} respondió ${r.status} (${url})`);
    } catch (e) {
      fallas.push(`${nombre} no responde (${url}): ${(e as Error).message}`);
    }
  }
  if (fallas.length) {
    process.env.CC_E2E_SIN_STACK = fallas.join("; ");
    console.warn(`\n[e2e] El stack local no está disponible, se saltarán las pruebas.\n  ${fallas.join("\n  ")}\n  Levántalo con: .\scripts\local.ps1 up\n`);
  }
}
