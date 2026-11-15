// Todas las fechas se muestran en la zona de México (CC-NFR-014); la API guarda UTC.
export const ZONA = "America/Mexico_City";

const formato = (d: Date, opciones: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat("es-MX", { timeZone: ZONA, ...opciones }).format(d);

export function fechaHora(iso: string): string {
  return formato(new Date(iso), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).replace(
    /\./g,
    "",
  );
}

export function fechaCorta(iso: string): string {
  return formato(new Date(iso), { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** Una fecha sin hora (`2026-11-13`) no se desplaza por zona horaria. */
export function fechaCivil(valor: string): string {
  const [a, m, d] = valor.split("-").map(Number);
  return new Intl.DateTimeFormat("es-MX", { timeZone: "UTC", day: "2-digit", month: "2-digit", year: "numeric" }).format(
    new Date(Date.UTC(a, m - 1, d, 12)),
  );
}
