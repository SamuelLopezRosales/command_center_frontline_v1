import type { components } from "@/api-client/generado/constancias";
import type { PaginaColaboradores } from "./tipos-externos";
import { solicitar, solicitarConEtag } from "@/api-client/http";
import type { FiltroHistorial, PaginaHistorial } from "./historial/tipos";

type Esq = components["schemas"];
export type Plantilla = Esq["cc_constancias__api__plantillas__Plantilla"];
export type Variable = Esq["VariableDto"];
export type Contenido = Esq["ContenidoPlantilla"];
export type Version = Esq["Version"];
export type VersionDetalle = Esq["VersionDetalle"];
export type ResultadoValidacion = Esq["ResultadoValidacion"];
export type Hallazgo = Esq["Hallazgo"];
export type VistaPrevia = Esq["VistaPreviaSalida"];
export type UrlDescarga = Esq["UrlDescarga"];

const P = "/api/v1/plantillas";

export const listarPlantillas = () => solicitar<Esq["PlantillasSalida"]>(P).then((r) => r.items);
export const obtenerPlantilla = (id: number) => solicitar<Plantilla>(`${P}/${id}`);
export const crearPlantilla = (cuerpo: Esq["PlantillaCrear"]) => solicitar<Plantilla>(P, { metodo: "POST", cuerpo });
export const actualizarPlantilla = (id: number, cuerpo: Esq["PlantillaActualizar"]) =>
  solicitar<Plantilla>(`${P}/${id}`, { metodo: "PATCH", cuerpo });
export const duplicarPlantilla = (id: number) => solicitar<Plantilla>(`${P}/${id}/duplicar`, { metodo: "POST" });
export const eliminarPlantilla = (id: number) => solicitar<void>(`${P}/${id}`, { metodo: "DELETE" });

export const listarVariables = () => solicitar<Esq["VariablesSalida"]>("/api/v1/constancias/variables").then((r) => r.items);

export const leerBorrador = (id: number) => solicitarConEtag<Esq["BorradorLeido"]>(`${P}/${id}/borrador`);
/** Guarda con `If-Match` (bloqueo optimista). Devuelve el ETag nuevo. */
export const guardarBorrador = (id: number, contenido: Contenido, etag: string | null) =>
  solicitarConEtag<Esq["BorradorGuardado"]>(`${P}/${id}/borrador`, {
    metodo: "PUT",
    cuerpo: contenido,
    encabezados: etag ? { "If-Match": etag } : undefined,
  });
export const validarBorrador = (id: number) =>
  solicitar<ResultadoValidacion>(`${P}/${id}/borrador/validar`, { metodo: "POST" });
export const publicar = (id: number, confirmarSensibles: boolean) =>
  solicitar<Version>(`${P}/${id}/publicar`, { metodo: "POST", cuerpo: { confirmar_sensibles: confirmarSensibles } });
export const listarVersiones = (id: number) => solicitar<Esq["VersionesSalida"]>(`${P}/${id}/versiones`).then((r) => r.items);
export const leerVersion = (id: number, numero: number) => solicitar<VersionDetalle>(`${P}/${id}/versiones/${numero}`);
export const restaurarVersion = (id: number, numero: number) =>
  solicitar<Version>(`${P}/${id}/versiones/${numero}/restaurar`, { metodo: "POST" });
export const vistaPrevia = (id: number, colaboradorId: number) =>
  solicitar<VistaPrevia>(`${P}/${id}/vista-previa`, {
    metodo: "POST",
    cuerpo: { colaborador_id: colaboradorId, usar_borrador: true },
  });

/** Búsqueda de colaboradores para elegir el "colaborador de prueba" de la vista previa. */
export const buscarColaboradores = (q: string) =>
  solicitar<PaginaColaboradores>("/api/v1/colaboradores", { consulta: { q, limite: 5 } });

// Historial y acciones sobre constancias emitidas.
export const listarHistorial = (f: FiltroHistorial) =>
  solicitar<PaginaHistorial>("/api/v1/constancias/historial", { consulta: { ...f } });
export const urlDeDescarga = (constanciaId: number) =>
  solicitar<UrlDescarga>(`/api/v1/constancias/${constanciaId}/descarga`, { metodo: "POST" });
/** CON-18 responde 202 sin cuerpo: `solicitar` lo intenta leer como JSON, por eso se tolera. */
export async function reenviarConstancia(constanciaId: number): Promise<void> {
  try {
    await solicitar<unknown>(`/api/v1/constancias/${constanciaId}/reenviar`, { metodo: "POST" });
  } catch (e) {
    if (!(e instanceof SyntaxError)) throw e;
  }
}
