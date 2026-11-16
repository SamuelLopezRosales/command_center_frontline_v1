// Ayudantes de las pruebas E2E que usan Python del repositorio (uv) para tareas que el navegador no hace.
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const aqui = dirname(fileURLToPath(import.meta.url));
export const RAIZ_REPO = join(aqui, "..", "..", "..");

export function python<T = unknown>(script: string, args: string[]): T {
  const salida = execFileSync("uv", ["run", "python", join(aqui, "apoyo", script), ...args], { cwd: RAIZ_REPO, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  return JSON.parse(salida.trim().split("\n").at(-1)!) as T;
}

export interface MensajeSalida {
  id: number;
  texto: string | null;
  interactivo: { action?: { sections?: { rows: { id: string; title: string }[] }[] } } | null;
  proposito: string | null;
}

/** Simula a Meta: mensaje entrante del colaborador hacia `wa-entrada.fifo`. */
export function escribirComoColaborador(waId: string, mensaje: { texto?: string; interactivo?: string }) {
  const args = ["enviar", waId, ...(mensaje.texto !== undefined ? ["--texto", mensaje.texto] : []), ...(mensaje.interactivo ? ["--interactivo", mensaje.interactivo] : [])];
  return python<{ wamid: string }>("wa.py", args);
}

/** Respuestas del bot (del outbox de whatsapp) después de `desde`; espera hasta que alguna contenga `contiene`. */
export function respuestasDelBot(waId: string, opciones: { contiene?: string; desde?: number; esperaSeg?: number } = {}) {
  const args = ["salida", waId, "--desde", String(opciones.desde ?? 0), "--espera", String(opciones.esperaSeg ?? 30), ...(opciones.contiene ? ["--contiene", opciones.contiene] : [])];
  return python<{ mensajes: MensajeSalida[]; agotado?: boolean }>("wa.py", args);
}

/** Cierra la ventana de 24 h de la conversación de un colaborador (escribe en la base local). */
export const envejecerConversacion = (numeroEmpleado: string, horas = 30) => python<{ actualizadas: number }>("wa.py", ["envejecer", numeroEmpleado, "--horas", String(horas)]);

/** Código de verificación de una constancia generada en el stack local (o `null` si no hay). */
export const codigoDeVerificacion = () => python<{ codigo: string | null }>("bd.py", ["codigo-verificacion"]).codigo;
