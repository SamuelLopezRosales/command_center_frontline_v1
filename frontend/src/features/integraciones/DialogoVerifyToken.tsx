import { useState } from "react";
import { mensajeDeError } from "@/shared/errores";
import { generarVerifyToken } from "./api";
import { Dialogo } from "./Dialogo";
import { t } from "./textos";

/**
 * Genera el token de verificación del webhook. El valor se muestra UNA sola vez: vive únicamente
 * en el estado de este componente (nunca en la caché de consultas, en storage, en consola ni en la
 * URL) y se descarta al cerrar el diálogo, que desmonta el componente. No usa `useMutation` para
 * que la respuesta tampoco quede en la caché de mutaciones.
 */
export function DialogoVerifyToken({ yaConfigurado, alCerrar }: { yaConfigurado: boolean; alCerrar: () => void }) {
  const [fase, setFase] = useState<"confirmar" | "generando" | "listo">("confirmar");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [copia, setCopia] = useState<"ok" | "error" | null>(null);

  async function generar() {
    setError(null);
    setFase("generando");
    try {
      setToken((await generarVerifyToken()).verify_token);
      setFase("listo");
    } catch (e) {
      setError(mensajeDeError(e) || t.generar.error);
      setFase("confirmar");
    }
  }

  async function copiar() {
    try {
      await navigator.clipboard.writeText(token);
      setCopia("ok");
    } catch {
      setCopia("error");
    }
  }

  // Mientras se genera no se puede cerrar: el token se perdería sin haberlo visto.
  const cerrar = () => fase !== "generando" && alCerrar();

  if (fase === "listo") {
    return (
      <Dialogo
        titulo={t.generar.resultadoTitulo}
        alCerrar={cerrar}
        acciones={
          <>
            <button type="button" className="btn btn-contorno" onClick={() => void copiar()}>
              {t.generar.copiar}
            </button>
            <button type="button" className="btn btn-primario" onClick={alCerrar}>
              {t.generar.cerrar}
            </button>
          </>
        }
      >
        <p className="alerta-info" role="alert">
          {t.generar.advertencia}
        </p>
        <p className="int-codigo-etiqueta" id="int-codigo-etiqueta">
          {t.generar.etiqueta}
        </p>
        <code className="int-codigo" aria-labelledby="int-codigo-etiqueta">
          {token}
        </code>
        {copia && (
          <p className={copia === "ok" ? "int-ok" : "alerta-error"} role="status">
            {copia === "ok" ? t.generar.copiado : t.generar.noCopiado}
          </p>
        )}
      </Dialogo>
    );
  }

  return (
    <Dialogo
      titulo={t.generar.titulo}
      alCerrar={cerrar}
      acciones={
        <>
          <button type="button" className="btn btn-contorno" disabled={fase === "generando"} onClick={alCerrar}>
            {t.generar.cancelar}
          </button>
          <button type="button" className="btn btn-primario" disabled={fase === "generando"} onClick={() => void generar()}>
            {fase === "generando" ? t.generar.generando : t.generar.generar}
          </button>
        </>
      }
    >
      <p>{t.generar.explicacion}</p>
      {yaConfigurado && <p className="alerta-info">{t.generar.reemplaza}</p>}
      {error && (
        <p className="alerta-error" role="alert">
          {error}
        </p>
      )}
    </Dialogo>
  );
}
