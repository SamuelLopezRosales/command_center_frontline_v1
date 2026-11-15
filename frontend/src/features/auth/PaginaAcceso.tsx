import { zodResolver } from "@hookform/resolvers/zod";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { z } from "zod";
import { Campo } from "@/shared/ui/Campo";
import { es } from "@/shared/i18n/es";
import { useSesion } from "@/shared/sesion/SesionProvider";
import type { PasoAcceso } from "@/shared/sesion/servicioAuth";

const t = es.auth;
const esquemaCredenciales = z.object({
  correo: z.string().min(1, t.requerido).email(t.correoInvalido),
  contrasena: z.string().min(1, t.requerido),
});
const esquemaCodigo = z.object({ codigo: z.string().regex(/^\d{6}$/, t.codigoSeis) });

function Marco({ children }: { children: React.ReactNode }) {
  return (
    <main className="acceso">
      <div className="tarjeta">
        <div className="marca">HONNE</div>
        {children}
      </div>
    </main>
  );
}

function mensaje(e: unknown): string {
  return e instanceof Error ? e.message : t.credencialesInvalidas;
}

/** Tres pasos: correo y contraseña, código TOTP (o enrolamiento) y entrada al dashboard. */
export function PaginaAcceso() {
  const { auth, estado, inactiva, completarAcceso } = useSesion();
  const navegar = useNavigate();
  const [paso, setPaso] = useState<PasoAcceso | null>(null);
  const [error, setError] = useState<string | null>(null);

  const credenciales = useForm({ resolver: zodResolver(esquemaCredenciales) });
  const codigo = useForm({ resolver: zodResolver(esquemaCodigo) });

  if (estado === "activa") return <Navigate to="/" replace />;

  async function terminar(siguiente: PasoAcceso) {
    if (siguiente.paso === "LISTO") {
      await completarAcceso();
      navegar("/", { replace: true });
    } else setPaso(siguiente);
  }

  const enviarCredenciales = credenciales.handleSubmit(async (v) => {
    setError(null);
    try {
      await terminar(await auth.iniciarSesion(v.correo, v.contrasena));
    } catch (e) {
      setError(mensaje(e));
    }
  });

  const enviarCodigo = codigo.handleSubmit(async (v) => {
    setError(null);
    try {
      await terminar(await auth.confirmarTotp(v.codigo));
    } catch (e) {
      setError(mensaje(e));
    }
  });

  if (paso?.paso === "TOTP" || paso?.paso === "ENROLAR_TOTP") {
    return (
      <Marco>
        <h2>{paso.paso === "ENROLAR_TOTP" ? t.enrolarTitulo : t.codigoTotp}</h2>
        <p className="subtitulo">{paso.paso === "ENROLAR_TOTP" ? t.enrolarAyuda : t.codigoTotpAyuda}</p>
        {paso.paso === "ENROLAR_TOTP" && (
          <div className="qr">
            <QRCodeSVG value={paso.uriQr} size={168} title="Código QR de la aplicación autenticadora" />
            <p>
              {t.claveManual}: <code>{paso.clave}</code>
            </p>
          </div>
        )}
        <form onSubmit={enviarCodigo} noValidate>
          {error && <div className="alerta-error" role="alert">{error}</div>}
          <Campo
            etiqueta={t.codigoTotp}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            error={codigo.formState.errors.codigo?.message}
            {...codigo.register("codigo")}
          />
          <button className="btn btn-primario" type="submit" disabled={codigo.formState.isSubmitting}>
            {t.verificar}
          </button>
        </form>
      </Marco>
    );
  }

  return (
    <Marco>
      <p className="subtitulo">{t.subtitulo}</p>
      {inactiva && <div className="alerta-info" role="status">{t.sesionExpirada}</div>}
      <form onSubmit={enviarCredenciales} noValidate>
        {error && <div className="alerta-error" role="alert">{error}</div>}
        <Campo
          etiqueta={t.correo}
          type="email"
          autoComplete="username"
          placeholder={t.correoEjemplo}
          error={credenciales.formState.errors.correo?.message}
          {...credenciales.register("correo")}
        />
        <Campo
          etiqueta={t.contrasena}
          type="password"
          autoComplete="current-password"
          error={credenciales.formState.errors.contrasena?.message}
          {...credenciales.register("contrasena")}
        />
        <button className="btn btn-primario" type="submit" disabled={credenciales.formState.isSubmitting}>
          {t.iniciar}
        </button>
      </form>
      <div className="enlaces">
        <Link to="/recuperar">{t.olvido}</Link>
        <br />
        <Link to="/registro">{t.registro}</Link>
      </div>
    </Marco>
  );
}

export { Marco };
