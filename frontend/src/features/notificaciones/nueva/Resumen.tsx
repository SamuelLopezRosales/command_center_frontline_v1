import { useId } from "react";
import type { Revision } from "../api";
import { HORARIO } from "../comun";
import { t } from "../textos";

export type Cuando = "AHORA" | "PROGRAMAR";

/** Texto de los excluidos por motivo: «5 sin consentimiento y 2 con estatus BAJA». */
export function textoExcluidos(r: Revision): string {
  const partes = (Object.entries(r.excluidos_por_motivo) as [string, number][])
    .filter(([, n]) => n > 0)
    .map(([motivo, n]) => `${n} ${t.motivosExclusion[motivo] ?? motivo}`);
  return partes.length > 1 ? `${partes.slice(0, -1).join(", ")} y ${partes[partes.length - 1]}` : (partes[0] ?? "");
}

function Barra({ etiqueta, valor, total, tono }: { etiqueta: string; valor: number; total: number; tono: "naranja" | "verde" }) {
  const ancho = total > 0 ? Math.round((valor / total) * 100) : 0;
  return (
    <li className="not-embudo-fila">
      <div className="not-embudo-texto">
        <span>{etiqueta}</span>
        <strong>{valor}</strong>
      </div>
      <div className="not-barra" aria-hidden="true">
        <div className={`not-barra-relleno not-barra-${tono}`} style={{ width: `${ancho}%` }} />
      </div>
    </li>
  );
}

export function Embudo({ revision }: { revision: Revision }) {
  const e = revision.embudo;
  return (
    <>
      <ul className="not-embudo" aria-label={t.nueva.embudo.aria}>
        <Barra etiqueta={t.nueva.embudo.seleccionados} valor={e.seleccionados} total={e.seleccionados} tono="naranja" />
        <Barra etiqueta={t.nueva.embudo.conConsentimiento} valor={e.con_consentimiento} total={e.seleccionados} tono="verde" />
        <Barra etiqueta={t.nueva.embudo.activos} valor={e.activos} total={e.seleccionados} tono="verde" />
        <Barra etiqueta={t.nueva.embudo.celularValido} valor={e.celular_valido} total={e.seleccionados} tono="verde" />
      </ul>
      {revision.total_excluidos > 0 ? (
        <div className="not-excluidos" role="status">
          <strong>{t.nueva.excluidosResumen(revision.total_excluidos, textoExcluidos(revision))}</strong>
          <small>{t.nueva.excluidosNota}</small>
        </div>
      ) : (
        <p className="not-suave" role="status">
          {t.nueva.sinExcluidos}
        </p>
      )}
    </>
  );
}

interface Props {
  revision: Revision | null;
  obsoleta: boolean;
  destinatarios: number;
  cuando: Cuando;
  alCambiarCuando: (c: Cuando) => void;
  fecha: string;
  hora: string;
  alCambiarFecha: (v: string) => void;
  alCambiarHora: (v: string) => void;
  errorProgramacion?: string;
  respaldo: boolean;
  alCambiarRespaldo: (v: boolean) => void;
  ocupado: boolean;
  alGuardar: () => void;
  alEnviar: () => void;
}

/** Panel «Resumen del envío»: embudo, horario y envío (cv1_09). */
export function Resumen(p: Props) {
  const idFecha = useId();
  const idHora = useId();
  const puedeEnviar = p.revision !== null && !p.obsoleta && p.destinatarios > 0 && !p.ocupado;
  return (
    <section className="tarjeta not-seccion not-resumen" aria-labelledby="not-resumen">
      <h2 id="not-resumen">{t.nueva.resumen}</h2>

      {p.revision ? (
        <Embudo revision={p.revision} />
      ) : (
        <p className="not-suave">{t.nueva.resumenVacio}</p>
      )}
      {p.revision && p.obsoleta && (
        <p className="alerta-info" role="status">
          {t.nueva.resumenObsoleto}
        </p>
      )}
      {p.revision && !p.obsoleta && p.destinatarios === 0 && (
        <p className="alerta-error" role="alert">
          {t.nueva.sinDestinatarios}
        </p>
      )}

      <p className="not-etiqueta-seccion">{t.nueva.cuando}</p>
      <div role="radiogroup" aria-label={t.nueva.cuando} className="not-cuando">
        <label>
          <input type="radio" name="not-cuando" checked={p.cuando === "AHORA"} onChange={() => p.alCambiarCuando("AHORA")} /> {t.nueva.ahora}
        </label>
        <label>
          <input type="radio" name="not-cuando" checked={p.cuando === "PROGRAMAR"} onChange={() => p.alCambiarCuando("PROGRAMAR")} />{" "}
          {t.nueva.programar}
        </label>
      </div>
      {p.cuando === "PROGRAMAR" && (
        <div className="not-programacion">
          <div className="campo">
            <label htmlFor={idFecha}>{t.nueva.fecha}</label>
            <input id={idFecha} type="date" value={p.fecha} aria-invalid={p.errorProgramacion ? true : undefined} onChange={(e) => p.alCambiarFecha(e.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor={idHora}>{t.nueva.hora}</label>
            <input id={idHora} type="time" value={p.hora} aria-invalid={p.errorProgramacion ? true : undefined} onChange={(e) => p.alCambiarHora(e.target.value)} />
          </div>
        </div>
      )}
      {p.errorProgramacion && (
        <span className="error not-error" role="alert">
          {p.errorProgramacion}
        </span>
      )}
      <p className="not-suave not-leyenda">{t.nueva.leyendaHorario(HORARIO.inicio, HORARIO.fin, HORARIO.zona)}</p>

      <label className="not-respaldo">
        <input type="checkbox" checked={p.respaldo} onChange={(e) => p.alCambiarRespaldo(e.target.checked)} />
        <span>
          {t.nueva.respaldo}
          <small className="not-suave">{t.nueva.respaldoAyuda}</small>
        </span>
      </label>

      <div className="not-respuestas">
        <p className="not-etiqueta-seccion">{t.nueva.respuestas}</p>
        <p>{t.nueva.respuestasTexto}</p>
      </div>

      <div className="not-pie-resumen">
        <button type="button" className="btn btn-contorno" disabled={p.ocupado} onClick={p.alGuardar}>
          {t.nueva.guardarBorrador}
        </button>
        <button type="button" className="btn btn-primario" disabled={!puedeEnviar} onClick={p.alEnviar}>
          {p.cuando === "PROGRAMAR" ? t.nueva.programarBoton(p.destinatarios) : t.nueva.enviar(p.destinatarios)}
        </button>
      </div>
    </section>
  );
}
