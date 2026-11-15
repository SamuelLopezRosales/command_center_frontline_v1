// Acceso de DESARROLLO para el stack local (docs/local.md): sustituye a Cognito con el proveedor
// de identidad que hace la pasarela local (scripts/local/pasarela.py). Mantiene el flujo real:
// correo + contraseña y después un paso TOTP, que aquí acepta cualquier código de 6 dígitos.
//
// Solo se usa con `import.meta.env.DEV && VITE_AUTH_LOCAL === "true"` (ver main.tsx). Este módulo
// no tiene efectos al importarse, por lo que la compilación de producción lo descarta entera.
import { ErrorAcceso, type PasoAcceso, type ServicioAuth } from "./servicioAuth";

const CLAVE_TOKEN = "cc-local-token";
const RUTA = "/api/dev/auth";

interface Opciones {
  /** Para pruebas: sustituye a `fetch`. */
  fetch?: typeof fetch;
  /** Para pruebas: sustituye a `sessionStorage` (el token vive solo en la pestaña). */
  almacen?: Pick<Storage, "getItem" | "setItem" | "removeItem">;
}

function expiracion(token: string): number {
  try {
    const carga = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return Number(JSON.parse(atob(carga)).exp) * 1000;
  } catch {
    return 0;
  }
}

export function crearAuthLocal(opciones: Opciones = {}): ServicioAuth {
  const llamar = opciones.fetch ?? ((...a: Parameters<typeof fetch>) => fetch(...a));
  const almacen = opciones.almacen ?? sessionStorage;
  let sesionPendiente: string | null = null;

  async function post(ruta: string, cuerpo: unknown): Promise<Record<string, string>> {
    const r = await llamar(`${RUTA}/${ruta}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
    const datos = (await r.json().catch(() => ({}))) as Record<string, string>;
    if (r.ok) return datos;
    if (datos.codigo === "CREDENCIALES") throw new ErrorAcceso("CREDENCIALES", "Correo o contraseña incorrectos.");
    if (datos.codigo === "CODIGO_INVALIDO" || datos.codigo === "SESION_VENCIDA")
      throw new ErrorAcceso("CODIGO_INVALIDO", "El código no es válido o venció.");
    throw new ErrorAcceso("DESCONOCIDO", "No se pudo completar la operación. ¿Está corriendo el stack local?");
  }

  const noDisponible = () => {
    throw new ErrorAcceso("DESCONOCIDO", "No está disponible en el acceso de desarrollo local.");
  };

  return {
    async iniciarSesion(correo, contrasena): Promise<PasoAcceso> {
      const r = await post("iniciar", { correo, contrasena });
      sesionPendiente = r.sesion;
      return { paso: "TOTP" };
    },
    async confirmarTotp(codigo): Promise<PasoAcceso> {
      if (!/^\d{6}$/.test(codigo)) throw new ErrorAcceso("CODIGO_INVALIDO", "El código no es válido o venció.");
      const r = await post("totp", { sesion: sesionPendiente ?? "", codigo });
      sesionPendiente = null;
      almacen.setItem(CLAVE_TOKEN, r.access_token);
      return { paso: "LISTO" };
    },
    async registrar() {
      return noDisponible();
    },
    async confirmarRegistro() {
      return noDisponible();
    },
    async solicitarRecuperacion() {
      // Igual que el flujo real: no revela si el correo existe.
    },
    async restablecerContrasena() {
      return noDisponible();
    },
    async haySesion() {
      const t = almacen.getItem(CLAVE_TOKEN);
      return Boolean(t) && expiracion(t!) > Date.now();
    },
    async token() {
      const t = almacen.getItem(CLAVE_TOKEN);
      return t && expiracion(t) > Date.now() ? t : null;
    },
    async cerrarSesion() {
      sesionPendiente = null;
      almacen.removeItem(CLAVE_TOKEN);
    },
  };
}
