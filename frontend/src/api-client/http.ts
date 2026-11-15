import { ErrorApi, leerProblema } from "@/shared/errores";

type ObtenerToken = () => Promise<string | null>;

let obtenerToken: ObtenerToken = async () => null;
let alExpirar: () => void = () => {};

export function configurarCliente(opciones: { token: ObtenerToken; alExpirar: () => void }) {
  obtenerToken = opciones.token;
  alExpirar = opciones.alExpirar;
}

export interface Opciones {
  metodo?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  consulta?: Record<string, string | number | boolean | undefined | null>;
  cuerpo?: unknown;
  encabezados?: Record<string, string>;
  publico?: boolean;
}

export function construirUrl(ruta: string, consulta?: Opciones["consulta"]): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(consulta ?? {})) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `${ruta}?${s}` : ruta;
}

async function encabezados(o: Opciones): Promise<Record<string, string>> {
  const h: Record<string, string> = { Accept: "application/json", ...o.encabezados };
  if (!o.publico) {
    const t = await obtenerToken();
    if (t) h.Authorization = `Bearer ${t}`;
  }
  if (o.cuerpo !== undefined) h["Content-Type"] = "application/json";
  return h;
}

async function ejecutar(ruta: string, o: Opciones): Promise<Response> {
  const r = await fetch(construirUrl(ruta, o.consulta), {
    method: o.metodo ?? "GET",
    headers: await encabezados(o),
    body: o.cuerpo === undefined ? undefined : JSON.stringify(o.cuerpo),
  });
  if (r.status === 401 && !o.publico) alExpirar();
  if (!r.ok) throw await leerProblema(r);
  return r;
}

export async function solicitar<T>(ruta: string, o: Opciones = {}): Promise<T> {
  const r = await ejecutar(ruta, o);
  if (r.status === 204) return undefined as T;
  const texto = await r.text();
  return (texto ? JSON.parse(texto) : undefined) as T;
}

/** Respuesta con ETag, para editar con If-Match. */
export async function solicitarConEtag<T>(ruta: string, o: Opciones = {}): Promise<{ datos: T; etag: string | null }> {
  const r = await ejecutar(ruta, o);
  return { datos: (await r.json()) as T, etag: r.headers.get("ETag") };
}

export { ErrorApi };
