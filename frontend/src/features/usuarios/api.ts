import type { components } from "@/api-client/generado/dashboard";
import { solicitar } from "@/api-client/http";

type Esq = components["schemas"];
export type UsuarioItem = Esq["UsuarioItem"];
export type Invitacion = Esq["InvitacionSalida"];
export type RegistroBitacora = Esq["RegistroBitacora"];
export type PaginaBitacora = Esq["BitacoraSalida"];

export const listarUsuarios = () => solicitar<Esq["UsuariosSalida"]>("/api/v1/usuarios").then((r) => r.items);
export const desactivarUsuario = (id: number) => solicitar<void>(`/api/v1/usuarios/${id}/desactivar`, { metodo: "POST" });
/** El código de la respuesta solo se entrega a quien llama: aquí no se guarda en ningún lado. */
export const crearInvitacion = (correo: string | null) =>
  solicitar<Invitacion>("/api/v1/usuarios/invitaciones", { metodo: "POST", cuerpo: correo ? { correo_destino: correo } : {} });

export interface FiltroBitacora {
  desde?: string;
  hasta?: string;
  usuario_id?: number;
  accion?: string;
  orden: "asc" | "desc";
  cursor?: string;
  limite: number;
}
export const consultarBitacora = (f: FiltroBitacora) => solicitar<PaginaBitacora>("/api/v1/bitacora", { consulta: { ...f } });
