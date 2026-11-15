import type { Contenido, Plantilla, Variable, Version } from "../api";

export const VARIABLES: Variable[] = [
  { nombre: "nombre_completo", etiqueta: "Nombre completo", grupo: "COLABORADOR", sensible: false },
  { nombre: "puesto", etiqueta: "Puesto", grupo: "COLABORADOR", sensible: false },
  { nombre: "organizacion.razon_social", etiqueta: "Razón social", grupo: "ORGANIZACION", sensible: false },
  { nombre: "rfc", etiqueta: "RFC", grupo: "SENSIBLES", sensible: true },
  { nombre: "nss", etiqueta: "NSS", grupo: "SENSIBLES", sensible: true },
  { nombre: "folio", etiqueta: "Folio", grupo: "SISTEMA", sensible: false },
];

export const CONTENIDO: Contenido = {
  esquema: 1,
  pagina: { tamano: "CARTA", margenes_cm: { sup: 2.5, inf: 2.5, izq: 2.5, der: 2.5 } },
  bloques: [
    { tipo: "logotipo", alineacion: "izquierda", ancho_cm: 5 },
    {
      tipo: "parrafo",
      alineacion: "centro",
      contenido: [
        { texto: "Hace constar que " },
        { var: "nombre_completo", negrita: true },
        { texto: ", con RFC " },
        { var: "rfc" },
      ],
    },
  ],
};

export const plantilla = (sobre: Partial<Plantilla> = {}): Plantilla => ({
  id: 7,
  nombre: "Constancia laboral",
  descripcion: "Antigüedad, puesto, área y sueldo mensual",
  activa: true,
  estado: "ACTIVA",
  version: 3,
  emitidas: 142,
  tiene_borrador: true,
  fecha_creacion: "2026-10-01T15:00:00Z",
  fecha_modificacion: "2026-11-12T18:00:00Z",
  ...sobre,
});

export const VERSIONES: Version[] = [
  { numero: 3, hash: "h3", fecha_creacion: "2026-11-12T18:00:00Z", vigente: true },
  { numero: 2, hash: "h2", fecha_creacion: "2026-11-05T18:00:00Z", vigente: false },
  { numero: 1, hash: "h1", fecha_creacion: "2026-10-10T18:00:00Z", vigente: false },
];
