import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { aplicarErroresDeCampo, mensajeDeError } from "@/shared/errores";
import { guardarMeta, type CambiosMeta, type EstadoMeta } from "./api";
import { BloqueCampo } from "./BloqueCampo";
import { DialogoVerifyToken } from "./DialogoVerifyToken";
import { esquemaMeta, type CampoMeta, type ValoresMeta } from "./esquema";
import { t } from "./textos";

type Secreto = "access_token" | "app_secret";  // pragma: allowlist secret

const valoresDe = (e: EstadoMeta): ValoresMeta => ({
  waba_id: e.waba_id ?? "",
  phone_number_id: e.phone_number_id ?? "",
  api_version: e.api_version,
  // Los secretos nunca se precargan: el servidor ni siquiera los entrega.
  access_token: "",
  app_secret: "",
  verify_token: "",
});

/** Solo viaja lo escrito y distinto de lo guardado: un campo vacío o sin cambios no se envía. */
export function calcularCambios(v: ValoresMeta, e: EstadoMeta): CambiosMeta {
  const c: CambiosMeta = {};
  if (v.waba_id && v.waba_id !== (e.waba_id ?? "")) c.waba_id = v.waba_id;
  if (v.phone_number_id && v.phone_number_id !== (e.phone_number_id ?? "")) c.phone_number_id = v.phone_number_id;
  if (v.api_version && v.api_version !== e.api_version) c.api_version = v.api_version;
  if (v.access_token) c.access_token = v.access_token;
  if (v.app_secret) c.app_secret = v.app_secret;
  if (v.verify_token) c.verify_token = v.verify_token;
  return c;
}

interface Props {
  estado: EstadoMeta;
  /** Recibe el estado nuevo (sin secretos) tras guardar. */
  alGuardar: (e: EstadoMeta) => void;
  /** Se llama al cerrar el diálogo del token generado, para releer el estado. */
  alGenerarToken: () => void;
}

/**
 * Formulario de credenciales. Los secretos son campos de contraseña que solo se escriben: si ya
 * están configurados se muestran enmascarados con «Reemplazar». Nada de esto va a la URL, al
 * almacenamiento del navegador, a la caché de consultas ni a la consola (el guardado no usa
 * `useMutation`), y tras guardar con éxito el formulario se reinicia y los campos quedan vacíos.
 */
export function FormularioMeta({ estado, alGuardar, alGenerarToken }: Props) {
  const form = useForm<ValoresMeta>({ resolver: zodResolver(esquemaMeta), defaultValues: valoresDe(estado) });
  const { register, handleSubmit, setValue, formState } = form;
  const [reemplazando, setReemplazando] = useState<Record<Secreto, boolean>>({ access_token: false, app_secret: false });
  const [propio, setPropio] = useState(false);
  const [generando, setGenerando] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);

  const errorDe = (c: CampoMeta) => formState.errors[c]?.message;

  const enviar = handleSubmit(async (valores) => {
    setAviso(null);
    const cambios = calcularCambios(valores, estado);
    if (Object.keys(cambios).length === 0) {
      setAviso({ tipo: "error", texto: t.formulario.sinCambios });
      return;
    }
    try {
      const nuevo = await guardarMeta(cambios);
      alGuardar(nuevo);
      // Los secretos salen del estado del formulario y del DOM.
      form.reset(valoresDe(nuevo));
      setReemplazando({ access_token: false, app_secret: false });
      setPropio(false);
      setAviso({ tipo: "ok", texto: t.formulario.guardado });
    } catch (e) {
      if (aplicarErroresDeCampo(e, form.setError as never)) return;
      setAviso({ tipo: "error", texto: mensajeDeError(e) || t.formulario.error });
    }
  });

  function cancelarReemplazo(campo: Secreto) {
    setValue(campo, "");
    form.clearErrors(campo);
    setReemplazando((r) => ({ ...r, [campo]: false }));
  }

  function campoSecreto(campo: Secreto) {
    const info = estado[campo];
    const etiqueta = t.campos[campo];
    const ayuda = t.ayudas[campo];
    const mostrarEntrada = !info.configurado || reemplazando[campo];
    return (
      <BloqueCampo etiqueta={etiqueta} ayuda={ayuda} error={errorDe(campo)} conControl={mostrarEntrada}>
        {({ id, describedBy, invalido }) =>
          mostrarEntrada ? (
            <div className="int-fila">
              <input
                id={id}
                type="password"
                autoComplete="new-password"
                autoCapitalize="off"
                spellCheck={false}
                aria-invalid={invalido || undefined}
                aria-describedby={describedBy}
                {...register(campo)}
              />
              {info.configurado && (
                <button type="button" className="btn btn-contorno" onClick={() => cancelarReemplazo(campo)}>
                  {t.secreto.cancelarReemplazo}
                </button>
              )}
            </div>
          ) : (
            <div className="int-fila" aria-describedby={describedBy}>
              <span className="int-enmascarado">{info.ultimos4 ? t.secreto.termina(info.ultimos4) : t.secreto.configurado}</span>
              <button
                type="button"
                className="btn btn-contorno"
                aria-label={`${t.secreto.reemplazar}: ${etiqueta}`}
                onClick={() => setReemplazando((r) => ({ ...r, [campo]: true }))}
              >
                {t.secreto.reemplazar}
              </button>
            </div>
          )
        }
      </BloqueCampo>
    );
  }

  const campoTexto = (campo: "waba_id" | "phone_number_id" | "api_version", inputMode?: "numeric") => (
    <BloqueCampo etiqueta={t.campos[campo]} ayuda={t.ayudas[campo]} error={errorDe(campo)}>
      {({ id, describedBy, invalido }) => (
        <input
          id={id}
          type="text"
          inputMode={inputMode}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={invalido || undefined}
          aria-describedby={describedBy}
          {...register(campo)}
        />
      )}
    </BloqueCampo>
  );

  return (
    <section className="tarjeta int-seccion" aria-labelledby="int-form-titulo">
      <h2 id="int-form-titulo">{t.formulario.titulo}</h2>
      <p className="int-suave">{t.formulario.soloLoEscrito}</p>
      <p className="alerta-info">{t.endpoint.texto}</p>
      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}
      <form onSubmit={(e) => void enviar(e)} noValidate autoComplete="off">
        {campoTexto("waba_id", "numeric")}
        {campoTexto("phone_number_id", "numeric")}
        {campoSecreto("access_token")}
        {campoSecreto("app_secret")}

        <BloqueCampo
          etiqueta={t.campos.verify_token}
          ayuda={t.ayudas.verify_token}
          error={errorDe("verify_token")}
          conControl={propio}
        >
          {({ id, describedBy, invalido }) => (
            <>
              <div className="int-fila">
                <span className="int-enmascarado">{estado.verify_token.configurado ? t.verify.estadoConfigurado : t.verify.estadoNo}</span>
                <button type="button" className="btn btn-contorno" onClick={() => setGenerando(true)}>
                  {t.verify.generar}
                </button>
                <button
                  type="button"
                  className="btn-enlace"
                  onClick={() => {
                    if (propio) {
                      setValue("verify_token", "");
                      form.clearErrors("verify_token");
                    }
                    setPropio(!propio);
                  }}
                >
                  {propio ? t.verify.noUsarPropio : t.verify.usarPropio}
                </button>
              </div>
              {propio && (
                <>
                  <input
                    id={id}
                    type="password"
                    autoComplete="new-password"
                    autoCapitalize="off"
                    spellCheck={false}
                    aria-invalid={invalido || undefined}
                    aria-describedby={describedBy}
                    {...register("verify_token")}
                  />
                  <span className="ayuda">{t.verify.propioAyuda}</span>
                </>
              )}
            </>
          )}
        </BloqueCampo>

        {campoTexto("api_version")}

        <div className="int-acciones">
          <button type="submit" className="btn btn-primario" disabled={formState.isSubmitting}>
            {formState.isSubmitting ? t.formulario.guardando : t.formulario.guardar}
          </button>
        </div>
      </form>

      {generando && (
        <DialogoVerifyToken
          yaConfigurado={estado.verify_token.configurado}
          alCerrar={() => {
            setGenerando(false);
            alGenerarToken();
          }}
        />
      )}
    </section>
  );
}
