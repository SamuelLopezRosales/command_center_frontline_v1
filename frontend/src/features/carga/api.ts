import { solicitar } from "@/api-client/http";
import type { components } from "@/api-client/generado/colaboradores";

type Esq = components["schemas"];
export type Carga = Esq["Carga"];
export type CargaDetalle = Esq["CargaDetalle"];
export type CargaIniciada = Esq["CargaIniciada"];
export type FilaCarga = Esq["FilaCarga"];
export type PaginaCargas = Esq["PaginaCargas"];
export type ResultadoFila = FilaCarga["resultado"];

export const CLAVE_CARGAS = ["cargas"] as const;
/** Cada cuánto se consulta el estado de una carga en proceso. */
export const INTERVALO_SONDEO_MS = 1500;
export const LIMITE_ARCHIVO = 5 * 1024 * 1024;

export const RUTA_PLANTILLA = "/api/v1/cargas/plantilla";
export const rutaErrores = (id: number) => `/api/v1/cargas/${id}/errores`;

export const apiCargas = {
  listar: (pagina: number, limite = 10) => solicitar<PaginaCargas>("/api/v1/cargas", { consulta: { pagina, limite } }),
  iniciar: (nombreArchivo: string, tamano: number) =>
    solicitar<CargaIniciada>("/api/v1/cargas", { metodo: "POST", cuerpo: { nombre_archivo: nombreArchivo, tamano } }),
  confirmar: (id: number) => solicitar<Carga>(`/api/v1/cargas/${id}/confirmar`, { metodo: "POST" }),
  detalle: (id: number, resultado: ResultadoFila | "", pagina: number, limite = 20) =>
    solicitar<CargaDetalle>(`/api/v1/cargas/${id}`, { consulta: { resultado: resultado || undefined, pagina, limite } }),
  cancelar: (id: number) => solicitar<Carga>(`/api/v1/cargas/${id}/cancelar`, { metodo: "POST" }),
};
