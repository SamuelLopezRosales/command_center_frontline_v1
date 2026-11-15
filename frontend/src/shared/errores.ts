// Errores problem+json de la API (design.md §9). Nunca se muestra el valor enviado.
export interface ErrorCampo {
  campo: string;
  codigo: string;
  mensaje: string;
}

export interface Problema {
  title: string;
  status: number;
  codigo: string;
  correlacion_id?: string;
  detalle?: Record<string, unknown>;
  errores?: ErrorCampo[];
}

export class ErrorApi extends Error {
  readonly status: number;
  readonly codigo: string;
  readonly correlacionId?: string;
  readonly detalle: Record<string, unknown>;
  readonly errores: ErrorCampo[];

  constructor(p: Problema) {
    super(p.title);
    this.name = "ErrorApi";
    this.status = p.status;
    this.codigo = p.codigo;
    this.correlacionId = p.correlacion_id;
    this.detalle = p.detalle ?? {};
    this.errores = p.errores ?? [];
  }

  /** Primer mensaje por campo. */
  porCampo(): Map<string, string> {
    const m = new Map<string, string>();
    for (const e of this.errores) if (!m.has(e.campo)) m.set(e.campo, e.mensaje);
    return m;
  }
}

export async function leerProblema(r: Response): Promise<ErrorApi> {
  try {
    const cuerpo = (await r.json()) as Partial<Problema>;
    return new ErrorApi({
      title: cuerpo.title ?? "No se pudo completar la operación.",
      status: r.status,
      codigo: cuerpo.codigo ?? "ERROR_HTTP",
      correlacion_id: cuerpo.correlacion_id,
      detalle: cuerpo.detalle,
      errores: cuerpo.errores,
    });
  } catch {
    return new ErrorApi({ title: "No se pudo completar la operación.", status: r.status, codigo: "ERROR_HTTP" });
  }
}

/** Aplica los errores por campo a React Hook Form (`setError`). Devuelve true si había alguno. */
export function aplicarErroresDeCampo(
  error: unknown,
  setError: (campo: never, e: { type: string; message: string }) => void,
): boolean {
  if (!(error instanceof ErrorApi) || error.errores.length === 0) return false;
  for (const e of error.errores) setError(e.campo as never, { type: e.codigo, message: e.mensaje });
  return true;
}

export function mensajeDeError(error: unknown): string {
  return error instanceof ErrorApi ? error.message : "No se pudo completar la operación. Intenta de nuevo.";
}
