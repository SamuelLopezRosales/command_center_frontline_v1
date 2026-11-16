import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { aplicarErroresDeCampo, mensajeDeError } from "@/shared/errores";
import { fechaHora } from "@/shared/fechas";
import { Campo } from "@/shared/ui/Campo";
import { crearInvitacion, type Invitacion } from "./api";
import { Dialogo } from "./Dialogo";
import { t } from "./textos";

const esquema = z.object({ correo: z.string().trim().email(t.invitacion.correoInvalido).or(z.literal("")) });
type Valores = z.infer<typeof esquema>;

/**
 * Crea una invitación (DSH-10). El código se muestra UNA sola vez: vive únicamente en el estado de
 * este componente (nunca en la caché de consultas, en storage, en consola ni en la URL) y se
 * descarta al cerrar el diálogo, que desmonta el componente.
 */
export function DialogoInvitacion({ alCerrar }: { alCerrar: () => void }) {
  const [invitacion, setInvitacion] = useState<Invitacion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copia, setCopia] = useState<"ok" | "error" | null>(null);
  const form = useForm<Valores>({ resolver: zodResolver(esquema), defaultValues: { correo: "" } });

  const crear = form.handleSubmit(async (v) => {
    setError(null);
    try {
      setInvitacion(await crearInvitacion(v.correo || null));
    } catch (e) {
      if (aplicarErroresDeCampo(e, form.setError as never)) return;
      setError(mensajeDeError(e) || t.invitacion.error);
    }
  });

  async function copiar() {
    if (!invitacion) return;
    try {
      await navigator.clipboard.writeText(invitacion.codigo);
      setCopia("ok");
    } catch {
      setCopia("error");
    }
  }

  if (invitacion) {
    return (
      <Dialogo
        titulo={t.invitacion.codigoTitulo}
        alCerrar={alCerrar}
        acciones={
          <>
            <button type="button" className="btn btn-contorno" onClick={() => void copiar()}>
              {t.invitacion.copiar}
            </button>
            <button type="button" className="btn btn-primario" onClick={alCerrar}>
              {t.invitacion.cerrar}
            </button>
          </>
        }
      >
        <p className="alerta-info" role="alert">
          {t.invitacion.advertencia}
        </p>
        <p className="usr-codigo-etiqueta" id="usr-codigo-etiqueta">
          {t.invitacion.codigoEtiqueta}
        </p>
        <code className="usr-codigo" aria-labelledby="usr-codigo-etiqueta">
          {invitacion.codigo}
        </code>
        <p className="usr-suave">{t.invitacion.expira(fechaHora(invitacion.fecha_expira))}</p>
        {copia && (
          <p className={copia === "ok" ? "usr-ok" : "alerta-error"} role="status">
            {copia === "ok" ? t.invitacion.copiado : t.invitacion.noCopiado}
          </p>
        )}
      </Dialogo>
    );
  }

  return (
    <Dialogo
      titulo={t.invitacion.titulo}
      alCerrar={alCerrar}
      acciones={
        <>
          <button type="button" className="btn btn-contorno" onClick={alCerrar}>
            {t.invitacion.cancelar}
          </button>
          <button type="submit" form="usr-form-invitacion" className="btn btn-primario" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? t.invitacion.creando : t.invitacion.crear}
          </button>
        </>
      }
    >
      <p className="usr-suave">{t.invitacion.ayuda}</p>
      {error && (
        <p className="alerta-error" role="alert">
          {error}
        </p>
      )}
      <form id="usr-form-invitacion" onSubmit={crear} noValidate>
        <Campo etiqueta={t.invitacion.correo} type="email" autoComplete="off" error={form.formState.errors.correo?.message} {...form.register("correo")} />
      </form>
    </Dialogo>
  );
}
