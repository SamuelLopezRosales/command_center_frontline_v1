import { solicitar } from "@/api-client/http";
import type { components } from "@/api-client/generado/notificaciones";

type Esq = components["schemas"];
export type PlantillaDeMeta = Esq["PlantillaDeMeta"];
export type ListadoDeMeta = Esq["ListadoDeMeta"];
export type ResultadoImportacion = Esq["ResultadoImportacion"];
export type ResultadoImportar = Esq["ResultadoImportar"];

const PM = "/api/v1/plantillas-mensaje";

export const CLAVE_DE_META = ["notificaciones", "plantillas", "de-meta"] as const;

/** Plantillas ya aprobadas en Meta: solo lectura y alta de lo elegido (nombre e idioma, nada más). */
export const apiImportarMeta = {
  listar: () => solicitar<ListadoDeMeta>(`${PM}/meta`),
  importar: (plantillas: { nombre: string; idioma: string }[]) =>
    solicitar<ResultadoImportar>(`${PM}/importar`, { metodo: "POST", cuerpo: { plantillas } }),
};

/** Se puede elegir: compatible, todavía no importada y sin conflicto de nombre. */
export const esImportable = (p: PlantillaDeMeta) => p.compatible && !p.ya_importada && !p.nombre_en_uso;

export const claveFila = (p: { nombre: string; idioma: string }) => `${p.nombre}|${p.idioma}`;
