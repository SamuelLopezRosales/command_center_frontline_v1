import { ZONA } from "@/shared/fechas";

/** Hora local de México (`16:02`) de un instante ISO. */
export function hora(iso: string): string {
  return new Intl.DateTimeFormat("es-MX", { timeZone: ZONA, hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
}

/** Fecha y hora de México para una etiqueta: `2026-11-15` y `08:00` a partir de un instante. */
export function partesLocales(iso: string): { fecha: string; hora: string } {
  const p = new Intl.DateTimeFormat("en-CA", {
    timeZone: ZONA,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso));
  const g = (tipo: string) => p.find((x) => x.type === tipo)?.value ?? "";
  const hh = g("hour") === "24" ? "00" : g("hour");
  return { fecha: `${g("year")}-${g("month")}-${g("day")}`, hora: `${hh}:${g("minute")}` };
}

/**
 * Instante ISO con la zona de México (UTC-6 fijo: México eliminó el horario de verano en 2022)
 * a partir de una fecha `AAAA-MM-DD` y una hora `HH:MM` locales.
 */
export function aInstanteMexico(fecha: string, horaLocal: string): string {
  return `${fecha}T${horaLocal}:00-06:00`;
}

/** `true` si `HH:MM` cae dentro de `[inicio, fin]` (ambos extremos inclusivos). */
export function dentroDeHorario(horaLocal: string, inicio: string, fin: string): boolean {
  return horaLocal >= inicio && horaLocal <= fin;
}

export function porcentaje(n: number): string {
  return `${Math.round(n)}%`;
}

export function entero(n: number): string {
  return new Intl.NumberFormat("es-MX").format(n);
}

/**
 * Las variables de una plantilla en orden de aparición: `"1"`, `"2"`... si es numerada o sus
 * nombres (`"guest_name"`) si es con nombre. Una respuesta sin `variables` (antigua) cae a 1..n.
 */
export function nombresDeVariables(p: { variables?: string[]; cantidad_variables: number }): string[] {
  if (p.variables && p.variables.length > 0) return p.variables;
  return Array.from({ length: p.cantidad_variables }, (_, i) => String(i + 1));
}

/** La plantilla usa variables con nombre (`{{guest_name}}`). */
export const esNombrada = (p: { formato_variables?: string }) => p.formato_variables === "NOMBRADO";
