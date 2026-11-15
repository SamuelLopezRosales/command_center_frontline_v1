import type { components } from "./generado/dashboard";
import { solicitar } from "./http";

export type UsuarioYo = components["schemas"]["UsuarioYo"];
export * from "./http";

export const api = {
  usuarioActual: () => solicitar<UsuarioYo>("/api/v1/usuarios/yo"),
  iniciarSesion: () => solicitar<void>("/api/v1/sesion/iniciar", { metodo: "POST" }),
};
