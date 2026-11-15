// Datos simulados compartidos por las pruebas de T-220 (colaboradores, campos, organizaciones).
import type { CampoDto, CampoFijoDto, ListadoCampos } from "@/features/campos/api";
import type { ColaboradorDetalle, ColaboradorFila } from "@/features/colaboradores/api";
import type { Organizacion, Planta } from "@/features/organizaciones/api";

export function json(cuerpo: unknown, estado = 200, encabezados: Record<string, string> = {}): Response {
  return new Response(cuerpo === undefined ? null : JSON.stringify(cuerpo), {
    status: estado,
    headers: { "Content-Type": "application/json", ...encabezados },
  });
}

export function problema(estado: number, codigo: string, title: string, extra: Record<string, unknown> = {}): Response {
  return json({ title, status: estado, codigo, ...extra }, estado);
}

export const FIJOS: CampoFijoDto[] = [
  { clave: "numero_empleado", nombre: "Número de empleado", tipo_dato: "TEXTO", obligatorio: true },
  { clave: "nombres", nombre: "Nombre(s)", tipo_dato: "TEXTO", obligatorio: true },
  { clave: "apellido_paterno", nombre: "Apellido paterno", tipo_dato: "TEXTO", obligatorio: true },
  { clave: "apellido_materno", nombre: "Apellido materno", tipo_dato: "TEXTO", obligatorio: true },
  { clave: "celular", nombre: "Celular con WhatsApp", tipo_dato: "TEXTO", obligatorio: true },
  { clave: "organizacion", nombre: "Organización", tipo_dato: "LISTA", obligatorio: true },
  { clave: "planta", nombre: "Planta o centro de trabajo", tipo_dato: "LISTA", obligatorio: true },
  { clave: "fecha_ingreso", nombre: "Fecha de ingreso", tipo_dato: "FECHA", obligatorio: true },
  { clave: "puesto", nombre: "Puesto", tipo_dato: "TEXTO", obligatorio: true },
  { clave: "tipo_empleado", nombre: "Tipo de empleado", tipo_dato: "LISTA", obligatorio: true },
  { clave: "estatus", nombre: "Estatus", tipo_dato: "LISTA", obligatorio: true },
];

export function campo(sobre: Partial<CampoDto> & Pick<CampoDto, "id" | "codigo_interno" | "clave" | "nombre_campo">): CampoDto {
  return {
    activo: true,
    es_sensible: false,
    es_sugerido: true,
    formato_validacion: null,
    obligatorio: false,
    opciones: [],
    orden: sobre.id,
    tipo_dato: "TEXTO",
    usada_en_plantillas: 0,
    ...sobre,
  };
}

export const CAMPO_AREA = campo({
  id: 1,
  codigo_interno: "CAMP-0001",
  clave: "area",
  nombre_campo: "Área",
  tipo_dato: "LISTA",
  opciones: [
    { id: 11, etiqueta: "Producción", valor: "PRODUCCION", descripcion: null, orden: 1, activo: true },
    { id: 12, etiqueta: "Almacén", valor: "ALMACEN", descripcion: "Bodega central", orden: 2, activo: true },
  ],
});
export const CAMPO_TURNO = campo({
  id: 3,
  codigo_interno: "CAMP-0003",
  clave: "turno",
  nombre_campo: "Turno",
  tipo_dato: "LISTA",
  usada_en_plantillas: 1,
  opciones: [{ id: 31, etiqueta: "Matutino", valor: "MATUTINO", descripcion: "08:00 – 17:00", orden: 1, activo: true }],
});
export const CAMPO_SUELDO = campo({ id: 5, codigo_interno: "CAMP-0005", clave: "sueldo", nombre_campo: "Sueldo (MXN)", tipo_dato: "NUMERO", es_sensible: true });
export const CAMPO_NSS = campo({ id: 8, codigo_interno: "CAMP-0008", clave: "nss", nombre_campo: "NSS", es_sensible: true, obligatorio: true });
export const CAMPO_RUTA = campo({ id: 4, codigo_interno: "CAMP-0004", clave: "ruta_transporte", nombre_campo: "Ruta de transporte", activo: false });
export const CAMPO_BONO = campo({
  id: 12,
  codigo_interno: "CAMP-0012",
  clave: "bono_productividad",
  nombre_campo: "Bono de productividad",
  tipo_dato: "NUMERO",
  es_sugerido: false,
  es_sensible: true,
});

export const DINAMICOS = [CAMPO_AREA, CAMPO_TURNO, CAMPO_RUTA, CAMPO_SUELDO, CAMPO_NSS, CAMPO_BONO];

export const listadoCampos = (dinamicos: CampoDto[] = DINAMICOS): ListadoCampos => ({ fijos: FIJOS, dinamicos });

export const ORGS: Organizacion[] = [
  {
    id: 1,
    clave: "ORG01",
    razon_social: "Empresa Grupo Industrial Norte",
    rfc: "GIN010101AB1",
    ciudad: "Apodaca",
    domicilio_fiscal: null,
    registro_patronal: null,
    nombre_firmante: null,
    cargo_firmante: null,
    correo_firmante: null,
    tiene_logotipo: true,
    activa: true,
  },
  {
    id: 2,
    clave: "ORG02",
    razon_social: "Servicios del Norte",
    rfc: null,
    ciudad: null,
    domicilio_fiscal: null,
    registro_patronal: null,
    nombre_firmante: null,
    cargo_firmante: null,
    correo_firmante: null,
    tiene_logotipo: false,
    activa: true,
  },
];

export const PLANTAS: Planta[] = [
  { id: 1, nombre: "Apodaca", activa: true },
  { id: 2, nombre: "Monterrey", activa: true },
];

export function fila(n: number, sobre: Partial<ColaboradorFila> = {}): ColaboradorFila {
  return {
    id: n,
    numero_empleado: `EMP-${String(n).padStart(4, "0")}`,
    nombre_completo: `Colaborador Número ${n}`,
    organizacion: { id: 1, nombre: "ORG01" },
    planta: { id: 1, nombre: "Apodaca" },
    puesto: "Analista",
    tipo_empleado: "ADMINISTRATIVO",
    estatus: "ACTIVO",
    celular: "******1234",
    fecha_ingreso: "2024-03-15",
    consentimiento_vigente: true,
    campos: {},
    ...sobre,
  };
}

export function detalle(sobre: Partial<ColaboradorDetalle> = {}): ColaboradorDetalle {
  return {
    id: 7,
    numero_empleado: "EMP-0007",
    nombres: "Ricardo",
    apellido_paterno: "Salinas",
    apellido_materno: "Ibarra",
    celular: "******5678",
    celular_invalido: false,
    organizacion: { id: 1, nombre: "ORG01" },
    planta: { id: 1, nombre: "Apodaca" },
    fecha_ingreso: "2023-01-10",
    puesto: "Supervisor de Almacén",
    tipo_empleado: "OPERATIVO",
    estatus: "ACTIVO",
    fecha_baja: null,
    fecha_modificacion: "2026-11-01T10:00:00Z",
    elegible: true,
    motivo_no_elegible: null,
    consentimiento: { otorgado: true, vigente: true, fecha: "2026-01-01", vigente_hasta: null },
    campos: { "CAMP-0001": "ALMACEN", "CAMP-0005": { presente: true }, "CAMP-0008": { presente: true } },
    ...sobre,
  };
}

export interface Llamada {
  url: string;
  metodo: string;
  init?: RequestInit;
  cuerpo?: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}

/** fetch simulado con enrutamiento por ruta y método. Devuelve las llamadas hechas. */
export function simularRutas(manejador: (url: URL, metodo: string, init?: RequestInit) => Response | undefined): Llamada[] {
  const llamadas: Llamada[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (entrada: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(entrada), "http://localhost");
      const metodo = init?.method ?? "GET";
      llamadas.push({ url: url.pathname + url.search, metodo, init, cuerpo: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      return manejador(url, metodo, init) ?? problema(404, "NO_ENCONTRADO", "No encontrado");
    }),
  );
  return llamadas;
}
