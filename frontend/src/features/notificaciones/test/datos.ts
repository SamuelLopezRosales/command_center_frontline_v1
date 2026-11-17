import type { Destinatario, Indicadores, Notificacion, PlantillaMensaje, Revision } from "../api";

export { json, problema, simulador, type Llamada } from "@/features/constancias/test/simulador";

export function notificacion(sobre: Partial<Notificacion> = {}): Notificacion {
  return {
    id: 1,
    titulo: "Aviso de cierre de nómina",
    modo: "GRUPO",
    estado: "COMPLETADA",
    canal: "PLANTILLA_META",
    audiencia_id: 3,
    audiencia_nombre: "Todos · Grupo Industrial Norte",
    colaborador_id: null,
    criterios: { op: "Y", items: [{ campo: "estatus", operador: "es", valor: "ACTIVO" }] },
    plantilla: { id: 5, nombre: "aviso_nomina_v2", estado_meta: "APROBADA" },
    variables: { "1": { origen: "COLABORADOR", campo: "nombre_completo" } },
    vista_previa: "Hola {{nombre_completo}}, el cierre de nómina de la quincena es hoy 12 nov.",
    respaldo_correo: false,
    zona_horaria: "America/Mexico_City",
    modo_envio: "AHORA",
    programada_para: null,
    revisada_en: "2026-11-12T21:55:00Z",
    confirmada_en: "2026-11-12T21:58:00Z",
    confirmada_por_usuario_id: 1,
    confirmada_fuera_horario: false,
    motivo_cancelacion: null,
    contadores: { seleccionados: 118, excluidos: 6, validos: 112, enviados: 112, entregados: 108, leidos: 84, respondieron: 7, fallidos: 1 },
    linea_de_tiempo: [
      { evento: "CREADA", en: "2026-11-12T21:50:00Z" },
      { evento: "CONFIRMADA", en: "2026-11-12T21:58:00Z" },
      { evento: "ENVIADA", en: "2026-11-12T22:00:00Z" },
    ],
    usuario_id: 1,
    fecha_creacion: "2026-11-12T21:50:00Z",
    fecha_envio: "2026-11-12T22:00:00Z",
    ...sobre,
  };
}

export const INDICADORES: Indicadores = {
  mes: "2026-11",
  enviadas: 1284,
  entregadas: 1233,
  leidas: 912,
  fallidas: 14,
  porcentaje_entregadas: 96,
  porcentaje_leidas: 71,
  conteos: { envios: 24, programadas: 2, borradores: 1 },
};

export function plantillaMensaje(sobre: Partial<PlantillaMensaje> = {}): PlantillaMensaje {
  return {
    id: 5,
    nombre: "recordatorio_uniformes_v1",
    categoria: "UTILITY",
    idioma: "es_MX",
    texto_con_variables: "Hola {{1}}, te recordamos que mañana {{2}} se entregan uniformes.",
    ejemplos: ["Ana", "13 nov"],
    cantidad_variables: 2,
    formato_variables: "POSICIONAL",
    variables: ["1", "2"],
    estado_meta: "APROBADA",
    id_plantilla_meta: "meta-1",
    motivo_rechazo: null,
    creada_por_usuario_id: 1,
    fecha_creacion: "2026-11-01T10:00:00Z",
    ...sobre,
  };
}

/** El ejemplo de cv1_09: 61, 56, 54 y 54; 7 excluidos (5 sin consentimiento y 2 en BAJA). */
export const REVISION_CV1_09: Revision = {
  embudo: { seleccionados: 61, con_consentimiento: 56, activos: 54, celular_valido: 54 },
  excluidos_por_motivo: { SIN_CONSENTIMIENTO: 5, ESTATUS_BAJA: 2, SIN_CELULAR_VALIDO: 0 },
  total_seleccionados: 61,
  total_excluidos: 7,
  revisada_en: "2026-11-15T15:00:00Z",
};

export function destinatario(sobre: Partial<Destinatario> = {}): Destinatario {
  return {
    id: 1,
    colaborador_id: 11,
    nombre: "Ana Lucía Ramírez Torres",
    planta: "Apodaca",
    celular_enmascarado: "+52 •• •••• 5678",
    estado: "LEIDO",
    motivo_exclusion: null,
    motivo_fallo: null,
    canal_usado: "WHATSAPP",
    conversacion_id: 70,
    intentos: 1,
    fecha_estado: "2026-11-12T22:02:00Z",
    ...sobre,
  };
}
