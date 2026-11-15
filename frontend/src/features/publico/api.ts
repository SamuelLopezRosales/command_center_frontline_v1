import type { components } from "@/api-client/generado/constancias";
import { solicitar } from "@/api-client/http";

export type Verificacion = components["schemas"]["Verificacion"];

/** CON-19. Sin sesión: no se envía token de acceso. */
export const verificar = (codigo: string) =>
  solicitar<Verificacion>(`/api/v1/publico/verificar/${encodeURIComponent(codigo)}`, { publico: true });

export type EstadoEnlace = "VIGENTE" | "NO_VIGENTE" | "ERROR";

/**
 * CON-20: `GET /d/{token}` solo valida y NO consume el enlace (el consumo es el POST de CON-21),
 * así que es seguro consultarlo al abrir la página. Devuelve HTML, no JSON, por eso no usa
 * `solicitar`. Sin credenciales, sin caché y sin Referer.
 */
export async function revisarEnlace(token: string, senal?: AbortSignal): Promise<EstadoEnlace> {
  try {
    const r = await fetch(`/d/${encodeURIComponent(token)}`, {
      method: "GET",
      headers: { Accept: "text/html" },
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal: senal,
    });
    if (r.ok) return "VIGENTE";
    if (r.status === 404 || r.status === 410) return "NO_VIGENTE";
    return "ERROR";
  } catch {
    return "ERROR";
  }
}

/** Acción del formulario de descarga (CON-21): el navegador envía el POST y sigue el 302 al PDF. */
export const rutaDescarga = (token: string) => `/d/${encodeURIComponent(token)}/descargar`;
