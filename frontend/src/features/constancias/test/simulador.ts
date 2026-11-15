import { vi } from "vitest";

// jsdom no implementa varias APIs de layout que usa ProseMirror: se parchean solo para estas pruebas.
export function parchearJsdom() {
  const rect = { x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, toJSON: () => ({}) };
  const lista = Object.assign([] as unknown[], { item: () => null });
  Range.prototype.getClientRects = () => lista as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => rect as DOMRect;
  document.elementFromPoint = () => null;
  Element.prototype.scrollIntoView = () => {};
}

export interface Llamada {
  metodo: string;
  ruta: string;
  url: string;
  encabezados: Record<string, string>;
  cuerpo: unknown;
}

type Valor = unknown | ((l: Llamada) => Response | Promise<Response>);

export function json(cuerpo: unknown, estado = 200, encabezados: Record<string, string> = {}): Response {
  return new Response(cuerpo === undefined ? null : JSON.stringify(cuerpo), {
    status: estado,
    headers: { "Content-Type": "application/json", ...encabezados },
  });
}

export function problema(estado: number, codigo: string, title: string, errores?: unknown[]): Response {
  return json({ title, status: estado, codigo, errores }, estado, { "Content-Type": "application/problem+json" });
}

/**
 * Simula fetch por `MÉTODO /ruta` (sin la consulta). Las llamadas quedan en el arreglo devuelto.
 * Un valor que no es función se entrega como JSON 200.
 */
export function simulador(rutas: Record<string, Valor>) {
  const llamadas: Llamada[] = [];
  const f = vi.fn(async (entrada: RequestInfo | URL, init?: RequestInit) => {
    const url = String(entrada);
    const ruta = url.split("?")[0]!;
    const metodo = (init?.method ?? "GET").toUpperCase();
    let cuerpo: unknown = undefined;
    if (typeof init?.body === "string") cuerpo = JSON.parse(init.body);
    const llamada: Llamada = { metodo, ruta, url, encabezados: { ...(init?.headers as Record<string, string> | undefined) }, cuerpo };
    llamadas.push(llamada);
    const v = rutas[`${metodo} ${ruta}`];
    if (v === undefined) return problema(404, "NO_ENCONTRADO", "No encontrado");
    if (typeof v === "function") return (v as (l: Llamada) => Response | Promise<Response>)(llamada);
    return json(v);
  });
  vi.stubGlobal("fetch", f);
  return llamadas;
}
