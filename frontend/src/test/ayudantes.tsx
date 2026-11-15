import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { SesionProvider } from "@/shared/sesion/SesionProvider";
import type { PasoAcceso, ServicioAuth } from "@/shared/sesion/servicioAuth";

/** Cognito simulado: todo configurable por prueba. */
export function authSimulado(sobre: Partial<ServicioAuth> = {}): ServicioAuth & { llamadas: string[] } {
  const llamadas: string[] = [];
  const registrar = <T,>(nombre: string, valor: T) => async () => {
    llamadas.push(nombre);
    return valor;
  };
  const base: ServicioAuth = {
    iniciarSesion: registrar<PasoAcceso>("iniciarSesion", { paso: "TOTP" }),
    confirmarTotp: registrar<PasoAcceso>("confirmarTotp", { paso: "LISTO" }),
    registrar: registrar("registrar", { requiereConfirmacion: true }),
    confirmarRegistro: registrar<void>("confirmarRegistro", undefined),
    solicitarRecuperacion: registrar<void>("solicitarRecuperacion", undefined),
    restablecerContrasena: registrar<void>("restablecerContrasena", undefined),
    haySesion: async () => false,
    token: async () => "token-de-prueba",
    cerrarSesion: registrar<void>("cerrarSesion", undefined),
  };
  return Object.assign({ ...base, ...sobre }, { llamadas });
}

export function renderizar(ui: ReactElement, opciones: { auth?: ServicioAuth; ruta?: string; limiteInactividadMs?: number } = {}) {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const auth = opciones.auth ?? authSimulado();
  return {
    auth,
    ...render(
      <QueryClientProvider client={cliente}>
        <MemoryRouter initialEntries={[opciones.ruta ?? "/"]}>
          <SesionProvider auth={auth} limiteInactividadMs={opciones.limiteInactividadMs}>
            {ui}
          </SesionProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

export const USUARIO_PRUEBA = {
  id: 1,
  empresa_id: 1,
  nombre: "David Bet",
  correo: "david@empresa.com",
  rol: "RH",
  permisos: ["colaboradores:ver"],
};

/** Simula fetch con respuestas por ruta. Devuelve las llamadas hechas. */
export function simularApi(rutas: Record<string, unknown | ((init?: RequestInit) => Response)>) {
  const llamadas: { url: string; init?: RequestInit }[] = [];
  const f = vi.fn(async (entrada: RequestInfo | URL, init?: RequestInit) => {
    const url = String(entrada);
    llamadas.push({ url, init });
    const clave = Object.keys(rutas).find((k) => url.startsWith(k));
    if (!clave) return new Response(JSON.stringify({ title: "No encontrado", status: 404, codigo: "NO_ENCONTRADO" }), { status: 404 });
    const v = rutas[clave];
    if (typeof v === "function") return (v as (i?: RequestInit) => Response)(init);
    return new Response(v === undefined ? null : JSON.stringify(v), { status: v === undefined ? 204 : 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", f);
  return llamadas;
}
