const MS_VENTANA = 24 * 60 * 60 * 1000;

/** Milisegundos que le quedan a la ventana de 24 horas (≤ 0 si ya cerró o no hay mensaje entrante). */
export function msRestantes(ultimoEntranteIso: string | null | undefined, ahora: number): number {
  if (!ultimoEntranteIso) return 0;
  return new Date(ultimoEntranteIso).getTime() + MS_VENTANA - ahora;
}

export function partesDeTiempo(ms: number): { horas: number; minutos: number } {
  const total = Math.max(0, Math.floor(ms / 60000));
  return { horas: Math.floor(total / 60), minutos: total % 60 };
}

/**
 * Variables de una plantilla de Meta, en orden: las numeradas (`{{1}}`) de menor a mayor número y,
 * si la plantilla las usa con nombre (`{{guest_name}}`), por primera aparición. Se devuelven como
 * cadenas ("1", "guest_name").
 */
export function variablesDe(texto: string): string[] {
  const vistas: string[] = [];
  for (const m of texto.matchAll(/\{\{([^{}]+)\}\}/g)) if (!vistas.includes(m[1]!)) vistas.push(m[1]!);
  return esNombrada(vistas) ? vistas : vistas.sort((a, b) => Number(a) - Number(b));
}

/** La plantilla usa variables con nombre (alguna no es un número). */
export function esNombrada(variables: string[]): boolean {
  return variables.some((v) => !/^\d+$/.test(v));
}

/** Rellena cada `{{variable}}` con su valor; las vacías quedan como están. */
export function armar(texto: string, valores: Record<string, string>): string {
  return texto.replace(/\{\{([^{}]+)\}\}/g, (m, n: string) => valores[n]?.trim() || m);
}
