// DSH-11 ya existe en el backend (T-213): la forma coincide con `HistorialSalida` de dashboard.json.
// Contrato: design.md §3.2, DSH-11 (`GET /api/v1/constancias/historial`).

export type EstadoEntrega = "PENDIENTE" | "ENTREGADA" | "FALLIDA";

export interface FiltroHistorial {
  desde?: string; // AAAA-MM-DD
  hasta?: string; // AAAA-MM-DD
  plantilla_id?: number;
  colaborador_id?: number;
  estado?: EstadoEntrega;
  q?: string;
  /** Cursor opaco de la página (DSH-11 pagina por cursor, no por número). */
  cursor?: string;
  limite?: number;
}

export interface ItemHistorial {
  /** Identificador de la constancia: lo piden CON-17 (descarga) y CON-18 (reenvío). */
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
  /** Cursor de la página siguiente; `null` si no hay más. */
  siguiente: string | null;
}
