import { ZONA } from "@/shared/fechas";

/** "12 nov 2026" en la zona de México (CC-NFR-014). */
export function fechaMedia(iso: string): string {
  return new Intl.DateTimeFormat("es-MX", { timeZone: ZONA, day: "numeric", month: "short", year: "numeric" })
    .format(new Date(iso))
    .replace(/\./g, "");
}
