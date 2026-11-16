/**
 * Configuración de ejecución de la SPA (T-139).
 *
 * El despliegue (CcFrontend) publica `/config.json` junto a la SPA con los identificadores de
 * Cognito, la región y la URL base de la API. Así el mismo paquete compilado sirve a cualquier
 * ambiente sin recompilar. Nunca contiene secretos: solo identificadores públicos.
 *
 * Si `/config.json` no existe (desarrollo con Vite, pruebas) se usan las variables
 * `VITE_COGNITO_*` de compilación. El acceso local de desarrollo (`VITE_AUTH_LOCAL`) no pasa por
 * aquí: lo decide `main.tsx`.
 */
export interface ConfigEjecucion {
  userPoolId: string;
  userPoolClientId: string;
  region: string;
  /** Vacío = mismo origen (CloudFront sirve la SPA y `/api`). */
  apiBaseUrl: string;
}

export const RUTA_CONFIG = "/config.json";

type Cargador = (url: string, init?: RequestInit) => Promise<Response>;

function texto(valor: unknown): string {
  return typeof valor === "string" ? valor.trim() : "";
}

export function validarConfig(crudo: unknown): ConfigEjecucion {
  const c = (crudo ?? {}) as Record<string, unknown>;
  const config: ConfigEjecucion = {
    userPoolId: texto(c.userPoolId),
    userPoolClientId: texto(c.userPoolClientId),
    region: texto(c.region),
    apiBaseUrl: texto(c.apiBaseUrl),
  };
  if (!config.userPoolId || !config.userPoolClientId) {
    throw new Error("La configuración de ejecución no trae userPoolId y userPoolClientId.");
  }
  return config;
}

export async function cargarConfig(
  cargador: Cargador = (url, init) => fetch(url, init),
  entorno: { VITE_COGNITO_USER_POOL_ID?: string; VITE_COGNITO_CLIENT_ID?: string } = import.meta.env,
): Promise<ConfigEjecucion> {
  try {
    const r = await cargador(RUTA_CONFIG, { cache: "no-store", headers: { Accept: "application/json" } });
    const tipo = r.headers.get("content-type") ?? "";
    // Un servidor de desarrollo devuelve index.html (200) para una ruta desconocida.
    if (r.ok && tipo.includes("json")) return validarConfig(await r.json());
  } catch {
    // Sin archivo o sin red: se cae a la configuración de compilación.
  }
  const alternativa = {
    userPoolId: entorno.VITE_COGNITO_USER_POOL_ID,
    userPoolClientId: entorno.VITE_COGNITO_CLIENT_ID,
    region: "",
    apiBaseUrl: "",
  };
  return validarConfig(alternativa);
}
