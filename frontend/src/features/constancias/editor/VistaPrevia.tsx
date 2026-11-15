import { useEffect, useState } from "react";
import { buscarColaboradores, vistaPrevia, type VistaPrevia as Resultado } from "../api";
import { mensajeDeError } from "@/shared/errores";
import { t } from "../textos";

interface Props {
  plantillaId: number;
  /** Guarda el borrador antes de pedir la vista previa; devuelve false si no se pudo. */
  guardarAntes: () => Promise<boolean>;
}

/**
 * Vista previa con los datos de un colaborador (CC-REQ-063). El HTML que devuelve la API se
 * muestra SOLO dentro de un iframe con `sandbox` sin permisos: ni scripts ni mismo origen.
 */
export function VistaPrevia({ plantillaId, guardarAntes }: Props) {
  const [q, setQ] = useState("");
  const [opciones, setOpciones] = useState<{ id: number; nombre: string }[]>([]);
  const [elegido, setElegido] = useState<{ id: number; nombre: string } | null>(null);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const texto = q.trim();
    if (texto.length < 2 || elegido) {
      setOpciones([]);
      return;
    }
    let vigente = true;
    const espera = setTimeout(() => {
      buscarColaboradores(texto)
        .then((p) => vigente && setOpciones(p.items.map((c) => ({ id: c.id, nombre: c.nombre_completo }))))
        .catch(() => vigente && setOpciones([]));
    }, 250);
    return () => {
      vigente = false;
      clearTimeout(espera);
    };
  }, [q, elegido]);

  async function generar() {
    if (!elegido) {
      setError(t.vistaPrevia.elegirPrimero);
      return;
    }
    setError(null);
    setCargando(true);
    try {
      if (!(await guardarAntes())) return;
      setResultado(await vistaPrevia(plantillaId, elegido.id));
    } catch (e) {
      setResultado(null);
      setError(mensajeDeError(e));
    } finally {
      setCargando(false);
    }
  }

  return (
    <section className="ed-seccion" aria-labelledby="ed-vp-titulo">
      <h2 id="ed-vp-titulo">{t.vistaPrevia.titulo}</h2>
      <div className="campo">
        <label htmlFor="ed-vp-colaborador">{t.vistaPrevia.colaborador}</label>
        <input
          id="ed-vp-colaborador"
          value={q}
          autoComplete="off"
          onChange={(e) => {
            setQ(e.target.value);
            setElegido(null);
          }}
        />
        <span className="ayuda">{t.vistaPrevia.colaboradorAyuda}</span>
      </div>
      {opciones.length > 0 && (
        <ul className="ed-opciones" aria-label={t.vistaPrevia.sugerencias}>
          {opciones.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                className="btn-enlace"
                onClick={() => {
                  setElegido(o);
                  setQ(o.nombre);
                  setOpciones([]);
                }}
              >
                {o.nombre}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn btn-contorno" onClick={() => void generar()} disabled={cargando}>
        {cargando ? t.vistaPrevia.cargando : t.vistaPrevia.ver}
      </button>
      {error && (
        <p className="alerta-error" role="alert">
          {error}
        </p>
      )}
      {resultado && (
        <>
          {resultado.faltantes.length > 0 && <p className="alerta-info">{t.vistaPrevia.faltantes(resultado.faltantes)}</p>}
          {resultado.desconocidas.length > 0 && <p className="alerta-error">{t.vistaPrevia.desconocidas(resultado.desconocidas)}</p>}
          <iframe className="ed-iframe" title={t.vistaPrevia.iframe} sandbox="" referrerPolicy="no-referrer" srcDoc={resultado.html} />
        </>
      )}
    </section>
  );
}
