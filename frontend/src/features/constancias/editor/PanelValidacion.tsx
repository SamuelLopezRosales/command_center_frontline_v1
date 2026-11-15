import type { Hallazgo, ResultadoValidacion } from "../api";
import { t } from "../textos";

interface Props {
  resultado: ResultadoValidacion | null;
  validando: boolean;
  error: string | null;
  alValidar: () => void;
}

function Fila({ h, tipo }: { h: Hallazgo; tipo: "error" | "aviso" }) {
  return (
    <li className="ed-hallazgo">
      <span className={tipo === "error" ? "insignia error" : "insignia proceso"}>{tipo === "error" ? t.validacion.error : t.validacion.aviso}</span>
      <span>
        {h.mensaje}
        {h.variables.length > 0 && <small className="ed-suave"> ({h.variables.join(", ")})</small>}
      </span>
    </li>
  );
}

/** Errores (bloquean la publicación) y avisos (no bloquean) de CON-09. */
export function PanelValidacion({ resultado, validando, error, alValidar }: Props) {
  return (
    <section className="ed-seccion" aria-labelledby="ed-val-titulo">
      <div className="ed-seccion-cabecera">
        <h2 id="ed-val-titulo">{t.validacion.titulo}</h2>
        <button type="button" className="btn-enlace" onClick={alValidar} disabled={validando}>
          {validando ? t.validacion.validando : t.validacion.validar}
        </button>
      </div>
      {error && (
        <p className="alerta-error" role="alert">
          {error}
        </p>
      )}
      {!resultado && !error && <p className="ed-suave">{t.validacion.pendiente}</p>}
      {resultado && (
        <ul className="ed-hallazgos" aria-live="polite">
          {resultado.errores.length === 0 ? (
            <li className="ed-hallazgo">
              <span className="insignia ok">{t.validacion.ok}</span>
              <span>{t.validacion.sinErrores}</span>
            </li>
          ) : (
            resultado.errores.map((h, i) => <Fila key={`e${i}`} h={h} tipo="error" />)
          )}
          {resultado.advertencias.length === 0 ? (
            <li className="ed-hallazgo">
              <span className="insignia ok">{t.validacion.ok}</span>
              <span>{t.validacion.sinAvisos}</span>
            </li>
          ) : (
            resultado.advertencias.map((h, i) => <Fila key={`a${i}`} h={h} tipo="aviso" />)
          )}
        </ul>
      )}
    </section>
  );
}
