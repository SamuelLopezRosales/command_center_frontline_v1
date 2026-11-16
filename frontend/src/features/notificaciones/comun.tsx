import { useEffect, useId, useRef, type ReactNode } from "react";
import { ErrorApi, mensajeDeError } from "@/shared/errores";
import { ZONA } from "@/shared/fechas";
import { t } from "./textos";

/** Horario de envío por defecto (design.md §6.3): 08:00 a 20:00, inclusivo, hora de México. */
export const HORARIO = { inicio: "08:00", fin: "20:00", zona: ZONA } as const;

const CLASE_ESTADO: Record<string, string> = {
  COMPLETADA: "ok",
  ENVIANDO: "proceso",
  PROGRAMADA: "info",
  CON_FALLAS: "error",
  BORRADOR: "neutro",
  CANCELADA: "neutro",
};

export function InsigniaEstado({ estado }: { estado: string }) {
  return <span className={`insignia not-${CLASE_ESTADO[estado] ?? "neutro"}`}>{t.estados[estado] ?? estado}</span>;
}

const CLASE_META: Record<string, string> = { APROBADA: "ok", EN_REVISION: "proceso", RECHAZADA: "error", BORRADOR: "neutro" };

export function InsigniaMeta({ estado }: { estado: string }) {
  return <span className={`insignia not-${CLASE_META[estado] ?? "neutro"}`}>{t.plantillas.estados[estado] ?? estado}</span>;
}

/** Mensaje en español para un error de la API: el catálogo del módulo primero, luego el de la API. */
export function mensajeError(e: unknown, extra: Record<string, string> = {}): string {
  if (e instanceof ErrorApi) {
    return extra[e.codigo] ?? t.errores[e.codigo] ?? e.message;
  }
  return mensajeDeError(e);
}

export function esCodigo(e: unknown, codigo: string): boolean {
  return e instanceof ErrorApi && e.codigo === codigo;
}

interface PropsDialogo {
  titulo: string;
  children: ReactNode;
  acciones: ReactNode;
  alCerrar: () => void;
}

/** Diálogo modal accesible: foco inicial y Escape para cerrar. */
export function Dialogo({ titulo, children, acciones, alCerrar }: PropsDialogo) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div className="not-fondo" onKeyDown={(e) => e.key === "Escape" && alCerrar()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={id} className="not-dialogo">
        <h2 id={id}>{titulo}</h2>
        {children}
        <div className="not-dialogo-acciones">{acciones}</div>
      </div>
    </div>
  );
}

/** Burbuja de WhatsApp con el texto de la plantilla (cv1_09 y cv1_10). */
export function BurbujaMensaje({ texto }: { texto: string }) {
  return (
    <div className="not-fondo-chat">
      <p className="not-burbuja">{texto}</p>
    </div>
  );
}
