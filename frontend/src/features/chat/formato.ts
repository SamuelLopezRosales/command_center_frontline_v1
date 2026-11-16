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

/** Variables `{{n}}` de una plantilla de Meta, en orden. */
export function variablesDe(texto: string): number[] {
  const numeros = new Set<number>();
  for (const m of texto.matchAll(/\{\{(\d+)\}\}/g)) numeros.add(Number(m[1]));
  return [...numeros].sort((a, b) => a - b);
}

export function armar(texto: string, valores: string[]): string {
  return texto.replace(/\{\{(\d+)\}\}/g, (_, n: string) => valores[Number(n) - 1] || `{{${n}}}`);
}
