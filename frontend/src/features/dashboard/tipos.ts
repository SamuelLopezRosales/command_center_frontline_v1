// TODO T-213: reemplazar por tipos generados (los endpoints DSH-01 a DSH-04 aún no existen en el backend).
// Contrato de design.md §3.2.

export interface ResumenDashboard {
  colaboradores_activos: number;
  constancias_mes: number;
  solicitudes_en_proceso: number;
  plantillas_activas: number;
  /** Verdadero si todas las cifras son cero (CC-REQ-014). */
  vacio: boolean;
}

export interface ItemSolicitud {
  id: number;
  colaborador_nombre: string;
  plantilla_nombre: string;
  version: number;
  estado: string;
}

export interface ItemConstancia {
  folio: string;
  colaborador_nombre: string;
  plantilla_nombre: string;
  version: number;
  fecha: string;
  estado_entrega: string;
}

export type TipoAlerta = "SIN_CONSENTIMIENTO" | "CONSTANCIA_FALLIDA" | "CAMPO_VACIO_EN_PLANTILLA";

export interface Alerta {
  tipo: TipoAlerta;
  titulo: string;
  detalle: string;
  total: number;
  enlace: string;
}
