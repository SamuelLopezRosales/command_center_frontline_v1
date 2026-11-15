import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { mensajeDeError } from "@/shared/errores";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { CLAVE_CARGAS, INTERVALO_SONDEO_MS, apiCargas, rutaErrores, type ResultadoFila } from "./api";
import "./carga.css";
import { descargarArchivo } from "./descargas";
import { claseEstadoCarga } from "./PaginaCarga";
import { textos as t } from "./textos";

const D = t.detalle;

export function DetalleCarga() {
  const id = Number(useParams().id);
  const cliente = useQueryClient();
  const { auth } = useSesion();
  const [resultado, setResultado] = useState<ResultadoFila | "">("");
  const [pagina, setPagina] = useState(1);
  const [error, setError] = useState<string | null>(null);

  // Seguimiento por sondeo mientras la carga está en proceso.
  const consulta = useQuery({
    queryKey: [...CLAVE_CARGAS, "detalle", id, resultado, pagina],
    queryFn: () => apiCargas.detalle(id, resultado, pagina),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.carga.estado === "EN_PROCESO" ? INTERVALO_SONDEO_MS : false),
  });

  const carga = consulta.data?.carga;
  const filas = consulta.data?.filas;
  const paginas = filas ? Math.max(1, Math.ceil(filas.total / filas.limite)) : 1;
  const hechas = carga ? carga.filas_ok + carga.filas_error : 0;
  const porcentaje = carga?.total_filas ? Math.min(100, Math.round((hechas / carga.total_filas) * 100)) : 0;

  async function cancelar() {
    setError(null);
    try {
      await apiCargas.cancelar(id);
      await cliente.invalidateQueries({ queryKey: CLAVE_CARGAS });
    } catch (e) {
      setError(mensajeDeError(e));
    }
  }

  async function bajarReporte() {
    setError(null);
    try {
      await descargarArchivo(rutaErrores(id), `errores_carga_${id}.csv`, await auth.token());
    } catch (e) {
      setError(mensajeDeError(e));
    }
  }

  return (
    <>
      <div className="encabezado">
        <div>
          <h1>{D.titulo(id)}</h1>
          <p>{carga?.nombre_archivo ?? " "}</p>
        </div>
        <Link className="btn btn-contorno" to="/cargas">
          {D.volver}
        </Link>
      </div>

      {error && (
        <div className="alerta-error" role="alert">
          {error}
        </div>
      )}
      {consulta.isPending && <p role="status">{t.cargando}</p>}
      {consulta.isError && (
        <div className="alerta-error" role="alert">
          {t.errorCarga}{" "}
          <button className="btn-enlace" onClick={() => void consulta.refetch()}>
            {t.reintentar}
          </button>
        </div>
      )}

      {carga && (
        <>
          <section className="tarjeta" aria-label={D.resumen} style={{ marginBottom: 24 }}>
            <h2>
              {D.resumen} <span className={`insignia ${claseEstadoCarga(carga.estado)}`}>{t.estados[carga.estado] ?? carga.estado}</span>
            </h2>

            {carga.estado === "EN_PROCESO" && (
              <div role="status">
                <p>{D.procesando}</p>
                <div className="car-barra" aria-hidden="true">
                  <span style={{ width: `${porcentaje}%` }} />
                </div>
                <p>{D.progreso(hechas, carga.total_filas)}</p>
              </div>
            )}
            {carga.estado === "CANCELADA" && <div className="alerta-info">{D.cancelada(carga.motivo_cierre)}</div>}

            <dl className="car-resumen">
              <div>
                <dt>{D.total}</dt>
                <dd>{carga.total_filas ?? "—"}</dd>
              </div>
              <div>
                <dt>{D.correctas}</dt>
                <dd>{carga.filas_ok}</dd>
              </div>
              <div>
                <dt>{D.conError}</dt>
                <dd>{carga.filas_error}</dd>
              </div>
              <div>
                <dt>{D.plantilla}</dt>
                <dd>{carga.version_plantilla}</dd>
              </div>
            </dl>

            <div className="car-acciones">
              {carga.filas_error > 0 && (
                <button className="btn btn-primario" onClick={() => void bajarReporte()}>
                  {D.reporte}
                </button>
              )}
              {carga.estado === "EN_PROCESO" && (
                <>
                  <button className="btn btn-peligro" onClick={() => void cancelar()}>
                    {D.cancelar}
                  </button>
                  <small>{D.cancelarAyuda}</small>
                </>
              )}
            </div>
          </section>

          <section className="tarjeta car-tabla" aria-labelledby="car-filas">
            <h2 id="car-filas">{D.filas}</h2>
            <div className="car-filtro" style={{ padding: "0 24px 12px" }}>
              <select
                aria-label={D.filtro}
                value={resultado}
                onChange={(e) => {
                  setResultado(e.target.value as ResultadoFila | "");
                  setPagina(1);
                }}
              >
                <option value="">{D.todos}</option>
                {(Object.keys(D.resultados) as ResultadoFila[]).map((r) => (
                  <option key={r} value={r}>
                    {D.resultados[r]}
                  </option>
                ))}
              </select>
            </div>
            <table className="tabla">
              <thead>
                <tr>
                  <th>{D.colFila}</th>
                  <th>{D.colResultado}</th>
                  <th>{D.colErrores}</th>
                </tr>
              </thead>
              <tbody>
                {(filas?.items ?? []).map((f) => (
                  <tr key={f.numero_fila}>
                    <td>{f.numero_fila}</td>
                    <td>
                      <span className={`insignia ${f.resultado === "ERROR" ? "error" : f.resultado === "OMITIDO" ? "neutro" : "ok"}`}>
                        {D.resultados[f.resultado]}
                      </span>
                    </td>
                    <td>
                      {f.errores.length > 0 && (
                        <ul className="car-errores">
                          {f.errores.map((e, i) => (
                            <li key={i}>{e.mensaje}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
                {(filas?.items.length ?? 0) === 0 && (
                  <tr>
                    <td colSpan={3}>{D.sinFilas}</td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="car-pie">
              <span>{D.pagina(pagina, paginas)}</span>
              <button className="btn btn-contorno" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
                {t.anterior}
              </button>
              <button className="btn btn-contorno" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
                {t.siguiente}
              </button>
            </div>
          </section>
        </>
      )}
    </>
  );
}
