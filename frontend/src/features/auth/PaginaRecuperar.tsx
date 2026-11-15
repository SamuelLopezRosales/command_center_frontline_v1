import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import { es } from "@/shared/i18n/es";
import { Campo } from "@/shared/ui/Campo";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { Marco } from "./PaginaAcceso";

const t = es.auth;
const fuerte = (s: string) => /[a-z]/.test(s) && /[A-Z]/.test(s) && /\d/.test(s) && /[^A-Za-z0-9]/.test(s);
const esquemaCorreo = z.object({ correo: z.string().min(1, t.requerido).email(t.correoInvalido) });
const esquemaNueva = z.object({
  codigo: z.string().trim().min(1, t.requerido),
  contrasena: z.string().min(12, t.contrasenaCorta).refine(fuerte, t.politica),
});

/** Recuperación de contraseña por código al correo (CC-REQ-006). */
export function PaginaRecuperar() {
  const { auth } = useSesion();
  const navegar = useNavigate();
  const [correo, setCorreo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const formCorreo = useForm({ resolver: zodResolver(esquemaCorreo) });
  const formNueva = useForm({ resolver: zodResolver(esquemaNueva) });

  const pedir = formCorreo.handleSubmit(async (v) => {
    setError(null);
    try {
      await auth.solicitarRecuperacion(v.correo);
      setCorreo(v.correo); // Siempre avanza: no se revela si el correo existe.
    } catch (e) {
      setError(e instanceof Error ? e.message : es.comun.errorGeneral);
    }
  });

  const restablecer = formNueva.handleSubmit(async (v) => {
    setError(null);
    try {
      await auth.restablecerContrasena(correo!, v.codigo, v.contrasena);
      navegar("/acceso", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : es.comun.errorGeneral);
    }
  });

  return (
    <Marco>
      <h2>{t.recuperarTitulo}</h2>
      {!correo ? (
        <form onSubmit={pedir} noValidate>
          {error && <div className="alerta-error" role="alert">{error}</div>}
          <Campo etiqueta={t.correo} type="email" autoComplete="username" error={formCorreo.formState.errors.correo?.message} {...formCorreo.register("correo")} />
          <button className="btn btn-primario" type="submit">{t.enviarCodigo}</button>
        </form>
      ) : (
        <form onSubmit={restablecer} noValidate>
          <div className="alerta-info" role="status">{t.confirmarAyuda}</div>
          {error && <div className="alerta-error" role="alert">{error}</div>}
          <Campo etiqueta={t.codigoCorreo} autoComplete="one-time-code" error={formNueva.formState.errors.codigo?.message} {...formNueva.register("codigo")} />
          <Campo
            etiqueta={t.nuevaContrasena}
            type="password"
            autoComplete="new-password"
            ayuda={t.politica}
            error={formNueva.formState.errors.contrasena?.message}
            {...formNueva.register("contrasena")}
          />
          <button className="btn btn-primario" type="submit">{t.restablecer}</button>
        </form>
      )}
      <div className="enlaces"><Link to="/acceso">{t.volver}</Link></div>
    </Marco>
  );
}
