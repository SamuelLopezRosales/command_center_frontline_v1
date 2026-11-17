import { solicitar } from "@/api-client/http";
import type { components as Wa } from "@/api-client/generado/whatsapp";
import type { components as Not } from "@/api-client/generado/notificaciones";

export type Conversacion = Wa["schemas"]["ConversacionItem"];
export type Mensaje = Wa["schemas"]["Mensaje"];
export type PaginaConversaciones = Wa["schemas"]["PaginaConversaciones"];
export type PaginaMensajes = Wa["schemas"]["PaginaMensajes"];
export type PlantillaMensaje = Not["schemas"]["PlantillaDto"];
export type EstadoConversacion = Conversacion["estado"];

const C = "/api/v1/conversaciones";

export interface FiltroConversaciones {
  notificacion_id?: number;
  asignada_a?: number;
  estado?: EstadoConversacion;
  cursor?: string;
  limite?: number;
}

export const listarConversaciones = (f: FiltroConversaciones) => solicitar<PaginaConversaciones>(C, { consulta: { ...f } });
export const listarMensajes = (id: number, cursor?: string) =>
  solicitar<PaginaMensajes>(`${C}/${id}/mensajes`, { consulta: { cursor, limite: 50 } });
export const enviarTexto = (id: number, texto: string) =>
  solicitar<{ mensaje_id: number }>(`${C}/${id}/mensajes`, { metodo: "POST", cuerpo: { texto } });
/** Plantilla numerada: `variables` en orden. Plantilla con nombre: `variables_nombradas` por nombre. */
export type ValoresPlantilla = { variables: string[] } | { variables_nombradas: Record<string, string> };
export const enviarPlantilla = (id: number, plantilla_mensaje_id: number, valores: ValoresPlantilla) =>
  solicitar<{ mensaje_id: number }>(`${C}/${id}/mensajes/plantilla`, { metodo: "POST", cuerpo: { plantilla_mensaje_id, ...valores } });
export const asignarConversacion = (id: number, usuario_id: number) =>
  solicitar<Conversacion>(`${C}/${id}/asignacion`, { metodo: "PUT", cuerpo: { usuario_id } });

/** Plantillas de mensaje aprobadas por Meta (NOT-07). */
export const listarPlantillasAprobadas = () =>
  solicitar<{ items: PlantillaMensaje[] }>("/api/v1/plantillas-mensaje", { consulta: { estado: "APROBADA", limite: 200 } }).then((r) => r.items);

/** Usuarios de la empresa (DSH-08): sirve para elegir a quién asignar. Solo con `usuarios:administrar`. */
export interface UsuarioAsignable {
  id: number;
  nombre: string;
  activo: boolean;
}
export const listarUsuariosAsignables = () => solicitar<{ items: UsuarioAsignable[] }>("/api/v1/usuarios").then((r) => r.items);
