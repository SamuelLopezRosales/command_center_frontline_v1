import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, configurarCliente, type UsuarioYo } from "@/api-client";
import { useInactividad } from "./inactividad";
import type { ServicioAuth } from "./servicioAuth";

interface Sesion {
  estado: "cargando" | "anonima" | "activa";
  usuario: UsuarioYo | null;
  inactiva: boolean;
  auth: ServicioAuth;
  /** Llamar tras completar el acceso (después del paso TOTP). */
  completarAcceso(): Promise<void>;
  cerrarSesion(): Promise<void>;
  tiene(permiso: string): boolean;
}

const Contexto = createContext<Sesion | null>(null);

export function useSesion(): Sesion {
  const c = useContext(Contexto);
  if (!c) throw new Error("useSesion fuera de SesionProvider");
  return c;
}

export function SesionProvider({ auth, children, limiteInactividadMs }: { auth: ServicioAuth; children: ReactNode; limiteInactividadMs?: number }) {
  const [estado, setEstado] = useState<Sesion["estado"]>("cargando");
  const [usuario, setUsuario] = useState<UsuarioYo | null>(null);
  const [inactiva, setInactiva] = useState(false);

  const cerrar = useCallback(
    async (porInactividad = false) => {
      await auth.cerrarSesion().catch(() => undefined);
      setUsuario(null);
      setEstado("anonima");
      setInactiva(porInactividad);
    },
    [auth],
  );

  useEffect(() => {
    configurarCliente({ token: () => auth.token(), alExpirar: () => void cerrar() });
  }, [auth, cerrar]);

  const cargarUsuario = useCallback(async () => {
    const u = await api.usuarioActual();
    setUsuario(u);
    setEstado("activa");
    setInactiva(false);
    // El registro de LOGIN no debe bloquear la entrada (DSH-06 es idempotente).
    void api.iniciarSesion().catch(() => undefined);
  }, []);

  useEffect(() => {
    let vivo = true;
    (async () => {
      if (await auth.haySesion()) {
        try {
          await cargarUsuario();
          return;
        } catch {
          /* token vencido o usuario inactivo: cae a anónima */
        }
      }
      if (vivo) setEstado("anonima");
    })();
    return () => {
      vivo = false;
    };
  }, [auth, cargarUsuario]);

  useInactividad(estado === "activa", () => void cerrar(true), limiteInactividadMs);

  const valor = useMemo<Sesion>(
    () => ({
      estado,
      usuario,
      inactiva,
      auth,
      completarAcceso: cargarUsuario,
      cerrarSesion: () => cerrar(false),
      tiene: (p) => usuario?.permisos.includes(p) ?? false,
    }),
    [estado, usuario, inactiva, auth, cargarUsuario, cerrar],
  );
  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}
