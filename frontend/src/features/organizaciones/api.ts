import { solicitar } from "@/api-client/http";
import type { components } from "@/api-client/generado/colaboradores";

type Esq = components["schemas"];
export type Organizacion = Esq["Organizacion"];
export type OrganizacionCrear = Esq["OrganizacionCrear"];
export type OrganizacionActualizar = Esq["OrganizacionActualizar"];
export type Planta = Esq["Planta"];
export type UrlSubida = Esq["UrlSubida"];

export const CLAVE_ORGANIZACIONES = ["organizaciones"] as const;
export const CLAVE_PLANTAS = ["plantas"] as const;

export const apiOrganizaciones = {
  listar: (soloActivas = false) =>
    solicitar<Esq["OrganizacionesSalida"]>("/api/v1/organizaciones", { consulta: { solo_activas: soloActivas } }).then((r) => r.items),
  crear: (o: OrganizacionCrear) => solicitar<Organizacion>("/api/v1/organizaciones", { metodo: "POST", cuerpo: o }),
  actualizar: (id: number, o: OrganizacionActualizar) =>
    solicitar<Organizacion>(`/api/v1/organizaciones/${id}`, { metodo: "PATCH", cuerpo: o }),
  solicitarLogotipo: (id: number, contentType: string, tamano: number) =>
    solicitar<UrlSubida>(`/api/v1/organizaciones/${id}/logotipo`, { metodo: "POST", cuerpo: { content_type: contentType, tamano } }),
  confirmarLogotipo: (id: number, s3Key: string) =>
    solicitar<Organizacion>(`/api/v1/organizaciones/${id}/logotipo/confirmar`, { metodo: "POST", cuerpo: { s3_key: s3Key } }),
};

export const apiPlantas = {
  listar: (soloActivas = false) =>
    solicitar<Esq["PlantasSalida"]>("/api/v1/plantas", { consulta: { solo_activas: soloActivas } }).then((r) => r.items),
  crear: (nombre: string) => solicitar<Planta>("/api/v1/plantas", { metodo: "POST", cuerpo: { nombre } }),
  actualizar: (id: number, p: Esq["PlantaActualizar"]) => solicitar<Planta>(`/api/v1/plantas/${id}`, { metodo: "PATCH", cuerpo: p }),
};

/** Subida directa a S3 con la URL firmada (sin credenciales de la API). */
export async function subirAS3(url: string, archivo: Blob, contentType: string): Promise<void> {
  const r = await fetch(url, { method: "PUT", headers: { "Content-Type": contentType }, body: archivo });
  if (!r.ok) throw new Error("No se pudo subir el archivo. Intenta de nuevo.");
}
