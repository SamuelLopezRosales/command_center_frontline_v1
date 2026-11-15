// Tipos de DSH-01 a DSH-04: salen del contrato generado (`contracts/openapi/dashboard.json`).
import type { components } from "@/api-client/generado/dashboard";

type Esquemas = components["schemas"];

export type ResumenDashboard = Esquemas["ResumenDashboard"];
export type ItemSolicitud = Esquemas["ItemSolicitud"];
export type ItemConstancia = Esquemas["ItemConstancia"];
export type Alerta = Esquemas["Alerta"];
export type TipoAlerta = Alerta["tipo"];
