import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorApi, mensajeDeError } from "@/shared/errores";
import { enviarPlantilla, enviarTexto, listarPlantillasAprobadas } from "./api";
import { armar, variablesDe } from "./formato";
import { t } from "./textos";

const LIMITE = 1000;

interface Props {
  conversacionId: number;
  ventanaAbierta: boolean;
  /** El servidor respondió 409 VENTANA_24H_CERRADA aunque la lista decía abierta. */
  forzadaPorServidor: boolean;
  alCerrarseVentana: () => void;
}

/**
 * Responder (WAP-03 y WAP-04): texto libre solo con la ventana abierta; con la ventana cerrada solo
 * se ofrece una plantilla aprobada. Un 409 del servidor cambia a modo plantilla y lo explica.
 */
export function Redactor({ conversacionId, ventanaAbierta, forzadaPorServidor, alCerrarseVentana }: Props) {
  const cliente = useQueryClient();
  const [quiereTexto, setQuiereTexto] = useState(true);
  const modoPlantilla = !ventanaAbierta || !quiereTexto;
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [enviando, setEnviando] = useState(false);

  const [texto, setTexto] = useState("");
  const [plantillaId, setPlantillaId] = useState("");
  const [valores, setValores] = useState<string[]>([]);

  const plantillas = useQuery({ queryKey: ["chat", "plantillas"], queryFn: listarPlantillasAprobadas, enabled: modoPlantilla });
  const plantilla = plantillas.data?.find((p) => String(p.id) === plantillaId);
  const variables = plantilla ? variablesDe(plantilla.texto_con_variables) : [];

  const refrescar = () => {
    void cliente.invalidateQueries({ queryKey: ["chat", "mensajes", conversacionId] });
    void cliente.invalidateQueries({ queryKey: ["chat", "conversaciones"] });
  };

  async function enviarLibre() {
    const limpio = texto.trim();
    if (!limpio) return setAviso({ tipo: "error", texto: t.redactor.textoVacio });
    setEnviando(true);
    setAviso(null);
    try {
      await enviarTexto(conversacionId, limpio);
      setTexto("");
      setAviso({ tipo: "ok", texto: t.redactor.enviado });
      refrescar();
    } catch (e) {
      if (e instanceof ErrorApi && e.status === 409 && e.codigo === "VENTANA_24H_CERRADA") {
        // No es un error genérico: la pantalla cambia al modo plantilla y lo explica.
        alCerrarseVentana();
        setAviso(null);
        refrescar();
      } else {
        setAviso({ tipo: "error", texto: mensajeDeError(e) || t.redactor.errorEnvio });
      }
    } finally {
      setEnviando(false);
    }
  }

  async function enviarConPlantilla() {
    if (!plantilla) return setAviso({ tipo: "error", texto: t.redactor.plantillaRequerida });
    const lista = variables.map((n) => (valores[n - 1] ?? "").trim());
    if (lista.some((v) => !v)) return setAviso({ tipo: "error", texto: t.redactor.variablesVacias });
    setEnviando(true);
    setAviso(null);
    try {
      await enviarPlantilla(conversacionId, plantilla.id, lista);
      setPlantillaId("");
      setValores([]);
      setAviso({ tipo: "ok", texto: t.redactor.enviado });
      refrescar();
    } catch (e) {
      setAviso({ tipo: "error", texto: mensajeDeError(e) || t.redactor.errorEnvio });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="chat-redactor" aria-label={t.redactor.titulo}>
      {!ventanaAbierta && (
        <div className="alerta-info" role="status">
          <strong>{t.redactor.ventanaCerradaTitulo}</strong>
          {forzadaPorServidor && <p className="chat-parrafo">{t.redactor.cambioPorServidor}</p>}
          <p className="chat-parrafo">{t.redactor.ventanaCerradaAyuda}</p>
        </div>
      )}
      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}

      {!modoPlantilla ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void enviarLibre();
          }}
        >
          <div className="campo">
            <label htmlFor="chat-texto">{t.redactor.texto}</label>
            <textarea id="chat-texto" rows={3} maxLength={LIMITE} placeholder={t.redactor.placeholder} value={texto} onChange={(e) => setTexto(e.target.value)} />
            <span className="ayuda">{t.redactor.limite(texto.length)}</span>
          </div>
          <div className="chat-acciones">
            <button type="submit" className="btn btn-primario" disabled={enviando}>
              {t.redactor.enviar}
            </button>
            <button type="button" className="btn-enlace" onClick={() => setQuiereTexto(false)}>
              {t.redactor.pasarAPlantilla}
            </button>
          </div>
        </form>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void enviarConPlantilla();
          }}
        >
          {plantillas.isError && (
            <p className="alerta-error" role="alert">
              {t.redactor.errorPlantillas}
            </p>
          )}
          {plantillas.data && plantillas.data.length === 0 && <p className="alerta-info">{t.redactor.sinPlantillas}</p>}
          <div className="campo">
            <label htmlFor="chat-plantilla">{t.redactor.plantilla}</label>
            <select
              id="chat-plantilla"
              value={plantillaId}
              onChange={(e) => {
                setPlantillaId(e.target.value);
                setValores([]);
              }}
            >
              <option value="">{t.redactor.elegirPlantilla}</option>
              {plantillas.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nombre}
                </option>
              ))}
            </select>
          </div>
          {plantilla &&
            variables.map((n) => (
              <div className="campo" key={n}>
                <label htmlFor={`chat-var-${n}`}>{t.redactor.variable(n)}</label>
                <input
                  id={`chat-var-${n}`}
                  value={valores[n - 1] ?? ""}
                  onChange={(e) =>
                    setValores((v) => {
                      const copia = [...v];
                      copia[n - 1] = e.target.value;
                      return copia;
                    })
                  }
                />
              </div>
            ))}
          {plantilla && (
            <div className="chat-previa" aria-label={t.redactor.vistaPrevia}>
              <span className="chat-suave">{t.redactor.vistaPrevia}</span>
              <p>{armar(plantilla.texto_con_variables, valores)}</p>
            </div>
          )}
          <div className="chat-acciones">
            <button type="submit" className="btn btn-primario" disabled={enviando}>
              {t.redactor.enviarPlantilla}
            </button>
            {ventanaAbierta && (
              <button type="button" className="btn-enlace" onClick={() => setQuiereTexto(true)}>
                {t.redactor.pasarATexto}
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}
