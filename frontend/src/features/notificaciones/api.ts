import { solicitar } from "@/api-client/http";
import type { components } from "@/api-client/generado/notificaciones";
import type { components as compColaboradores } from "@/api-client/generado/colaboradores";
import type { components as compCampos } from "@/api-client/generado/campos";

type Esq = components["schemas"];
export type Notificacion = Esq["NotificacionDto"];
export type NotificacionCrear = Esq["NotificacionCrear"];
export type NotificacionActualizar = Esq["NotificacionActualizar"];
export type Confirmar = Esq["Confirmar"];
export type PaginaNotificaciones = Esq["PaginaNotificaciones"];
export type Indicadores = Esq["Indicadores"];
export type Revision = Esq["Revision"];
export type Destinatario = Esq["DestinatarioDto"];
export type PaginaDestinatarios = Esq["PaginaDestinatarios"];
export type PlantillaMensaje = Esq["PlantillaDto"];
export type PlantillaMensajeCrear = Esq["PlantillaCrear"];
export type Audiencia = Esq["AudienciaDto"];
export type VariableAsignada = Esq["VariableAsignada"];
export type Pestana = "envios" | "programadas" | "borradores";
export type EstadoNotificacion = Notificacion["estado"];
export type EstadoDestinatario = Destinatario["estado"];
export type ColaboradorFila = compColaboradores["schemas"]["ColaboradorFila"];
export type CampoDto = compCampos["schemas"]["CampoDto"];

const N = "/api/v1/notificaciones";
const PM = "/api/v1/plantillas-mensaje";

export const CLAVES = {
  listado: ["notificaciones", "listado"] as const,
  indicadores: ["notificaciones", "indicadores"] as const,
  plantillas: ["notificaciones", "plantillas"] as const,
  detalle: (id: number) => ["notificaciones", "detalle", id] as const,
  destinatarios: (id: number) => ["notificaciones", "destinatarios", id] as const,
};

export const apiNotificaciones = {
  listar: (pestana: Pestana) => solicitar<PaginaNotificaciones>(N, { consulta: { pestana, limite: 50 } }),
  indicadores: () => solicitar<Indicadores>(`${N}/indicadores`),
  detalle: (id: number) => solicitar<Notificacion>(`${N}/${id}`),
  crear: (cuerpo: NotificacionCrear) => solicitar<Notificacion>(N, { metodo: "POST", cuerpo }),
  actualizar: (id: number, cuerpo: NotificacionActualizar) => solicitar<Notificacion>(`${N}/${id}`, { metodo: "PATCH", cuerpo }),
  revisar: (id: number) => solicitar<Revision>(`${N}/${id}/revisar`, { metodo: "POST" }),
  confirmar: (id: number, cuerpo: Confirmar) => solicitar<Notificacion>(`${N}/${id}/confirmar`, { metodo: "POST", cuerpo }),
  cancelar: (id: number) => solicitar<Notificacion>(`${N}/${id}/cancelar`, { metodo: "POST", cuerpo: {} }),
  duplicar: (id: number) => solicitar<Notificacion>(`${N}/${id}/duplicar`, { metodo: "POST" }),
  reintentar: (id: number, confirmarFueraHorario: boolean) =>
    solicitar<Notificacion>(`${N}/${id}/reintentar`, { metodo: "POST", cuerpo: { confirmar_fuera_horario: confirmarFueraHorario } }),
  destinatarios: (id: number) => solicitar<PaginaDestinatarios>(`${N}/${id}/destinatarios`, { consulta: { limite: 200 } }),
};

export const apiPlantillasMensaje = {
  listar: (estado?: PlantillaMensaje["estado_meta"]) =>
    solicitar<Esq["PaginaPlantillas"]>(PM, { consulta: { estado, limite: 200 } }),
  crear: (cuerpo: PlantillaMensajeCrear) => solicitar<PlantillaMensaje>(PM, { metodo: "POST", cuerpo }),
  duplicar: (id: number) => solicitar<PlantillaMensaje>(`${PM}/${id}/duplicar`, { metodo: "POST" }),
  enviarARevision: (id: number) => solicitar<PlantillaMensaje>(`${PM}/${id}/enviar-revision`, { metodo: "POST" }),
  sincronizar: (id: number) => solicitar<PlantillaMensaje>(`${PM}/${id}/sincronizar`, { metodo: "POST" }),
};

export const apiAudiencias = {
  listar: () => solicitar<Esq["PaginaAudiencias"]>("/api/v1/audiencias", { consulta: { estado: "activas", limite: 200 } }),
};

/** Colaboradores para el modo INDIVIDUAL (el celular llega enmascarado desde la API). */
export const buscarColaboradores = (q: string) =>
  solicitar<compColaboradores["schemas"]["PaginaColaboradores"]>("/api/v1/colaboradores", {
    consulta: { q, estatus: "ACTIVO", limite: 8 },
  });
