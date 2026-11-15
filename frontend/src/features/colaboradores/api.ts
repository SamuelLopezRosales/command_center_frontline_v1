import { solicitar, solicitarConEtag } from "@/api-client/http";
import type { components } from "@/api-client/generado/colaboradores";

type Esq = components["schemas"];
export type ColaboradorFila = Esq["ColaboradorFila"];
export type ColaboradorDetalle = Esq["ColaboradorDetalle"];
export type ColaboradorCrear = Esq["ColaboradorCrear"];
export type ColaboradorActualizar = Esq["ColaboradorActualizar"];
export type PaginaColaboradores = Esq["PaginaColaboradores"];

export interface FiltrosListado {
  q: string;
  organizacion_id: string;
  planta_id: string;
  estatus: string;
  tipo_empleado: string;
  /** Códigos internos de campos dinámicos a incluir en cada fila. */
  columnas: string[];
  pagina: number;
  limite: number;
}

export const CLAVE_COLABORADORES = ["colaboradores"] as const;

function urlListado(f: FiltrosListado): string {
  const q = new URLSearchParams();
  const texto = f.q.trim();
  if (texto) q.set("q", texto);
  if (f.organizacion_id) q.set("organizacion_id", f.organizacion_id);
  if (f.planta_id) q.set("planta_id", f.planta_id);
  if (f.estatus) q.set("estatus", f.estatus);
  if (f.tipo_empleado) q.set("tipo_empleado", f.tipo_empleado);
  for (const c of f.columnas) q.append("columnas", c);
  q.set("pagina", String(f.pagina));
  q.set("limite", String(f.limite));
  return `/api/v1/colaboradores?${q.toString()}`;
}

const base = (id: number) => `/api/v1/colaboradores/${id}`;

export const apiColaboradores = {
  listar: (f: FiltrosListado) => solicitar<PaginaColaboradores>(urlListado(f)),
  /** El detalle devuelve ETag; la edición lo envía en If-Match (sin él, 428). */
  detalle: (id: number) => solicitarConEtag<ColaboradorDetalle>(base(id)),
  crear: (c: ColaboradorCrear) => solicitar<ColaboradorDetalle>("/api/v1/colaboradores", { metodo: "POST", cuerpo: c }),
  actualizar: (id: number, cambios: ColaboradorActualizar, etag: string | null) =>
    solicitar<ColaboradorDetalle>(base(id), {
      metodo: "PATCH",
      cuerpo: cambios,
      encabezados: etag ? { "If-Match": etag } : undefined,
    }),
  baja: (id: number, fechaBaja: string) =>
    solicitar<ColaboradorDetalle>(`${base(id)}/baja`, { metodo: "POST", cuerpo: { fecha_baja: fechaBaja } }),
  reactivar: (id: number, consentimiento: boolean) =>
    solicitar<ColaboradorDetalle>(`${base(id)}/reactivar`, { metodo: "POST", cuerpo: { consentimiento } }),
  consentimiento: (id: number, otorgado: boolean) =>
    solicitar<ColaboradorDetalle>(`${base(id)}/consentimiento`, { metodo: "PUT", cuerpo: { otorgado } }),
};
