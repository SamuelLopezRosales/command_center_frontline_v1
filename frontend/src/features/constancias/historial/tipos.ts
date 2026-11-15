// TODO T-213: reemplazar por tipos generados cuando exista DSH-11 en el OpenAPI.
// Contrato: design.md §3.2, DSH-11 (`GET /api/v1/constancias/historial`).

export type EstadoEntrega = "PENDIENTE" | "ENTREGADA" | "FALLIDA";

export interface FiltroHistorial {
  desde?: string; // AAAA-MM-DD
  hasta?: string; // AAAA-MM-DD
  plantilla_id?: number;
  colaborador_id?: number;
  estado?: EstadoEntrega;
  q?: string;
  pagina?: number;
  limite?: number;
}

export interface ItemHistorial {
  /**
   * HALLAZGO: DSH-11 no lista el identificador de la constancia, pero CON-17 (descarga) y CON-18
   * (reenvío) lo exigen en la ruta (`/constancias/{constancia_id}/...`). Se asume `id`; T-213
   * debe agregarlo a `ItemHistorial`.
   */
  id: number;
  folio: string;
  colaborador_nombre: string;
  plantilla_nombre: string;
  version: number;
  fecha: string;
  canal: string;
  estado_entrega: EstadoEntrega;
}

export interface PaginaHistorial {
  items: ItemHistorial[];
  total: number;
  pagina: number;
  limite: number;
}
