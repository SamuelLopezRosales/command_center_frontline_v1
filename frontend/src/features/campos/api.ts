import { solicitar } from "@/api-client/http";
import type { components } from "@/api-client/generado/campos";

type Esq = components["schemas"];
export type CampoDto = Esq["CampoDto"];
export type CampoFijoDto = Esq["CampoFijoDto"];
export type ListadoCampos = Esq["ListadoCampos"];
export type CampoCrear = Esq["CampoCrear"];
export type CampoActualizar = Partial<Esq["CampoActualizar"]>;
export type OpcionDto = Esq["OpcionDto"];
export type OpcionCrear = Esq["OpcionCrear"];
export type OpcionActualizar = Esq["OpcionActualizar"];
export type TipoDato = CampoDto["tipo_dato"];

export const apiCampos = {
  /** CAM-01. Trae todos (activos e inactivos); las pestañas filtran en pantalla. */
  listar: (estado: "todos" | "activos" | "inactivos" = "todos") =>
    solicitar<ListadoCampos>("/api/v1/campos", { consulta: { estado, tipo: "todos" } }),
  crear: (c: CampoCrear) => solicitar<CampoDto>("/api/v1/campos", { metodo: "POST", cuerpo: c }),
  actualizar: (id: number, c: CampoActualizar) => solicitar<CampoDto>(`/api/v1/campos/${id}`, { metodo: "PATCH", cuerpo: c }),
  eliminar: (id: number) => solicitar<void>(`/api/v1/campos/${id}`, { metodo: "DELETE" }),
  crearOpcion: (id: number, o: OpcionCrear) => solicitar<OpcionDto>(`/api/v1/campos/${id}/opciones`, { metodo: "POST", cuerpo: o }),
  actualizarOpcion: (id: number, opcionId: number, o: OpcionActualizar) =>
    solicitar<OpcionDto>(`/api/v1/campos/${id}/opciones/${opcionId}`, { metodo: "PATCH", cuerpo: o }),
};

export const CLAVE_CAMPOS = ["campos"] as const;
