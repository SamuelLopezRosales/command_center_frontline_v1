import type { components } from "@/api-client/generado/notificaciones";
import { solicitar } from "@/api-client/http";

type Esq = components["schemas"];
export type EstadoMeta = Esq["EstadoMetaDto"];
export type CambiosMeta = Esq["ActualizarMeta"];
export type PruebaMeta = Esq["PruebaMetaDto"];
export type ResultadoPrueba = Esq["ResultadoPruebaDto"];

const R = "/api/v1/integraciones/meta";

/** Clave de la consulta del estado. Nunca contiene secretos: el servidor solo manda los últimos 4. */
export const CLAVE_ESTADO = ["integraciones", "meta"] as const;

export const leerEstadoMeta = () => solicitar<EstadoMeta>(R);

/**
 * Los secretos viajan solo en el cuerpo de estas llamadas. Se usan funciones simples (no
 * `useMutation`) para que los valores enviados no queden en la caché de mutaciones.
 */
export const guardarMeta = (cambios: CambiosMeta) => solicitar<EstadoMeta>(R, { metodo: "PUT", cuerpo: cambios });
/** El token generado solo se entrega a quien llama: aquí no se guarda en ningún lado. */
export const generarVerifyToken = () => solicitar<Esq["TokenGeneradoDto"]>(`${R}/verify-token:generar`, { metodo: "POST" });
export const probarMeta = () => solicitar<PruebaMeta>(`${R}/probar`, { metodo: "POST" });
