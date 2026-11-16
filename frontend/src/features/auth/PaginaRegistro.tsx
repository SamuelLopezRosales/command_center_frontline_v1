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

const esquema = z.object({
  nombre: z.string().trim().min(1, t.requerido),
  correo: z.string().min(1, t.requerido).email(t.correoInvalido),
  contrasena: z.string().min(12, t.contrasenaCorta).refine(fuerte, t.politica),
  codigoInvitacion: z.string().trim().min(1, t.requerido),
});
// Con registro abierto no hay código de invitación: el resto de la validación es la misma.
const esquemaAbierto = esquema.extend({ codigoInvitacion: z.string().trim().optional() });
const esquemaConfirmar = z.object({ codigo: z.string().trim().min(1, t.requerido) });

/** Registro con código de invitación (CC-REQ-008), o sin él en ambientes de registro abierto. Pantalla sin diseño: validación visual pendiente (PQ-09). */
export function PaginaRegistro() {
  const { auth } = useSesion();
  const navegar = useNavigate();
  const [correoPendiente, setCorreoPendiente] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abierto = auth.registroAbierto === true;
  const form = useForm({ resolver: zodResolver(abierto ? esquemaAbierto : esquema) });
  const confirmar = useForm({ resolver: zodResolver(esquemaConfirmar) });

  const enviar = form.handleSubmit(async (v) => {
    setError(null);
    try {
      const r = await auth.registrar(v);
      if (r.requiereConfirmacion) setCorreoPendiente(v.correo);
      else navegar("/acceso", { replace: true });
    } catch (e) {
      // Mensaje genérico: no se revela si el código o el correo fallaron (D-02).
      setError(e instanceof Error ? e.message : t.registroNoPermitido);
    }
  });

  const enviarConfirmacion = confirmar.handleSubmit(async (v) => {
    setError(null);
    try {
      await auth.confirmarRegistro(correoPendiente!, v.codigo);
      navegar("/acceso", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : t.registroNoPermitido);
    }
  });

  if (correoPendiente) {
    return (
      <Marco>
        <h2>{t.confirmarTitulo}</h2>
        <p className="subtitulo">{t.confirmarAyuda}</p>
        <form onSubmit={enviarConfirmacion} noValidate>
          {error && <div className="alerta-error" role="alert">{error}</div>}
          <Campo etiqueta={t.codigoCorreo} autoComplete="one-time-code" error={confirmar.formState.errors.codigo?.message} {...confirmar.register("codigo")} />
          <button className="btn btn-primario" type="submit">{t.confirmar}</button>
        </form>
      </Marco>
    );
  }

  return (
    <Marco>
      <h2>{t.registroTitulo}</h2>
      <form onSubmit={enviar} noValidate>
        {error && <div className="alerta-error" role="alert">{error}</div>}
        <Campo etiqueta={t.nombre} autoComplete="name" error={form.formState.errors.nombre?.message} {...form.register("nombre")} />
        <Campo etiqueta={t.correo} type="email" autoComplete="email" error={form.formState.errors.correo?.message} {...form.register("correo")} />
        <Campo
          etiqueta={t.contrasena}
          type="password"
          autoComplete="new-password"
          ayuda={t.politica}
          error={form.formState.errors.contrasena?.message}
          {...form.register("contrasena")}
        />
        {!abierto && (
          <Campo etiqueta={t.codigoInvitacion} autoComplete="off" error={form.formState.errors.codigoInvitacion?.message} {...form.register("codigoInvitacion")} />
        )}
        <button className="btn btn-primario" type="submit" disabled={form.formState.isSubmitting}>{t.crearCuenta}</button>
      </form>
      <div className="enlaces"><Link to="/acceso">{t.yaTienesCuenta}</Link></div>
    </Marco>
  );
}
