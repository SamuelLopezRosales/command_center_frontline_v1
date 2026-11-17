import { useState } from "react";
import { ErrorApi, mensajeDeError } from "@/shared/errores";
import { probarMeta, type PruebaMeta, type ResultadoPrueba } from "./api";
import { t } from "./textos";

type Estado =
  | { fase: "reposo" }
  | { fase: "probando" }
  | { fase: "listo"; prueba: PruebaMeta }
  | { fase: "error"; mensaje: string };

type Veredicto = "ok" | "falla" | "pendiente" | "sin_probar";

const ICONO: Record<Veredicto, string> = { ok: "✓", falla: "✗", pendiente: "…", sin_probar: "–" };
const TEXTO: Record<Veredicto, string> = {
  ok: t.prueba.correcto,
  falla: t.prueba.fallo,
  pendiente: t.prueba.pendienteWebhook,
  sin_probar: t.prueba.noProbado,
};

/** Cada renglón dice su resultado con ícono y texto, no solo con color. */
function Renglon({ nombre, veredicto, detalle }: { nombre: string; veredicto: Veredicto; detalle?: string }) {
  return (
    <li className={`int-renglon int-renglon-${veredicto}`}>
      <span className="int-icono" aria-hidden="true">
        {ICONO[veredicto]}
      </span>
      <div>
        <strong>{nombre}</strong>: <span className="int-veredicto">{TEXTO[veredicto]}</span>
        {detalle && <p className="int-detalle">{detalle}</p>}
      </div>
    </li>
  );
}

const veredictoDe = (r: ResultadoPrueba | undefined): Veredicto => (!r ? "sin_probar" : r.ok ? "ok" : "falla");

/** «Probar conexión»: consulta la API de Meta con lo guardado. El resultado no se guarda en caché. */
export function ProbarConexion() {
  const [estado, setEstado] = useState<Estado>({ fase: "reposo" });

  async function probar() {
    setEstado({ fase: "probando" });
    try {
      setEstado({ fase: "listo", prueba: await probarMeta() });
    } catch (e) {
      if (e instanceof ErrorApi && e.codigo === "META_NO_CONFIGURADA") setEstado({ fase: "error", mensaje: t.prueba.sinConfigurar });
      else setEstado({ fase: "error", mensaje: mensajeDeError(e) || t.prueba.error });
    }
  }

  const prueba = estado.fase === "listo" ? estado.prueba : null;
  const buscar = (clave: ResultadoPrueba["clave"]) => prueba?.resultados.find((r) => r.clave === clave);
  const webhook = buscar("webhook");
  const numero = prueba?.numero;

  return (
    <section className="tarjeta int-seccion" aria-labelledby="int-prueba-titulo">
      <h2 id="int-prueba-titulo">{t.prueba.titulo}</h2>
      <p className="int-suave">{t.prueba.ayuda}</p>
      <button type="button" className="btn btn-primario" disabled={estado.fase === "probando"} onClick={() => void probar()}>
        {estado.fase === "probando" ? t.prueba.probando : t.prueba.boton}
      </button>

      {estado.fase === "error" && (
        <p className="alerta-error int-separado" role="alert">
          {estado.mensaje}
        </p>
      )}

      {prueba && (
        <div className="int-resultado" role="status">
          <p className={prueba.ok ? "int-ok" : "int-falla"}>
            <strong>{prueba.ok ? t.prueba.resumenOk : t.prueba.resumenFalla}</strong>
          </p>
          <ul className="int-renglones">
            <Renglon nombre={t.prueba.renglones.token} veredicto={veredictoDe(buscar("token"))} detalle={buscar("token")?.detalle} />
            <Renglon nombre={t.prueba.renglones.numero} veredicto={veredictoDe(buscar("numero"))} detalle={buscar("numero")?.detalle} />
            <Renglon nombre={t.prueba.renglones.waba} veredicto={veredictoDe(buscar("waba"))} detalle={buscar("waba")?.detalle} />
          </ul>
          {numero && (
            <dl className="int-numero" aria-label={t.prueba.datosNumero}>
              <dt>{t.prueba.nombreVerificado}</dt>
              <dd>{numero.nombre_verificado ?? t.prueba.sinDato}</dd>
              <dt>{t.prueba.numeroMostrado}</dt>
              <dd>{numero.numero_mostrado ?? t.prueba.sinDato}</dd>
              <dt>{t.prueba.calidad}</dt>
              <dd>{numero.calidad ?? t.prueba.sinDato}</dd>
            </dl>
          )}
          <ul className="int-renglones">
            <Renglon
              nombre={t.prueba.renglones.webhook}
              veredicto={webhook ? (webhook.ok ? "ok" : "pendiente") : "sin_probar"}
              detalle={webhook?.detalle}
            />
          </ul>
          {webhook && !webhook.ok && <p className="int-suave">{t.prueba.webhookNota}</p>}
        </div>
      )}
    </section>
  );
}
