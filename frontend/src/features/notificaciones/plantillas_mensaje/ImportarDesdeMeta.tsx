import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi } from "@/shared/errores";
import { CLAVES } from "../api";
import { mensajeError } from "../comun";
import { t } from "../textos";
import {
  apiImportarMeta,
  CLAVE_DE_META,
  claveFila,
  esImportable,
  type PlantillaDeMeta,
  type ResultadoImportacion,
} from "./api";
import { tImportar as ti } from "./textos";
import "../notificaciones.css";
import "./importar.css";

const CLASE_ESTADO: Record<string, string> = { APPROVED: "ok", PENDING: "proceso", PAUSED: "proceso", REJECTED: "error", DISABLED: "error" };
const CLASE_RESULTADO: Record<string, string> = { IMPORTADA: "ok", YA_EXISTIA: "info", OMITIDA: "proceso" };

/** Mensaje en español de un error de la consulta o de la importación. */
function describirError(e: unknown, porDefecto: string): { noConfigurada: boolean; texto: string } {
  if (e instanceof ErrorApi) {
    if (e.codigo === "META_NO_CONFIGURADA") return { noConfigurada: true, texto: ti.noConfigurada };
    // Meta: el servidor ya trae el motivo en español (token vencido, permisos, tasa...).
    if (e.codigo === "ERROR_PROVEEDOR_META") return { noConfigurada: false, texto: e.message || ti.errorMeta };
    return { noConfigurada: false, texto: mensajeError(e) };
  }
  return { noConfigurada: false, texto: porDefecto };
}

function InsigniasImportacion({ p }: { p: PlantillaDeMeta }) {
  return (
    <div className="imp-insignias">
      {p.compatible ? (
        <span className="insignia not-ok">{ti.compatible}</span>
      ) : (
        <span className="insignia not-neutro">
          {p.motivo_incompatible ? ti.noCompatible(p.motivo_incompatible) : ti.noCompatibleSinMotivo}
        </span>
      )}
      {p.ya_importada && <span className="insignia not-info">{ti.yaImportada}</span>}
      {p.nombre_en_uso && <span className="insignia not-proceso">{ti.nombreEnUso}</span>}
    </div>
  );
}

function Resumen({ items }: { items: ResultadoImportacion[] }) {
  const cuenta = (r: string) => items.filter((i) => i.resultado === r).length;
  return (
    <section aria-labelledby="imp-resumen-titulo">
      <h3 id="imp-resumen-titulo">{ti.resumen.titulo}</h3>
      <p className="imp-resumen-totales" role="status">
        {ti.resumen.totales(cuenta("IMPORTADA"), cuenta("YA_EXISTIA"), cuenta("OMITIDA"))}
      </p>
      <div className="imp-tabla-caja">
        <table className="imp-tabla" aria-label={ti.resumen.tablaAria}>
          <thead>
            <tr>
              <th scope="col">{ti.columnas.plantilla}</th>
              <th scope="col">{ti.columnas.idioma}</th>
              <th scope="col">{ti.columnas.importacion}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={claveFila(i)}>
                <td className="imp-nombre">{i.nombre}</td>
                <td>{i.idioma}</td>
                <td>
                  <span className={`insignia not-${CLASE_RESULTADO[i.resultado] ?? "neutro"}`}>
                    {i.resultado === "OMITIDA"
                      ? i.motivo
                        ? ti.resumen.omitidaMotivo(i.motivo)
                        : ti.resumen.omitidaSinMotivo
                      : (ti.resumen.resultados[i.resultado] ?? i.resultado)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface Props {
  alCerrar: () => void;
  /** Se llama al cerrar si se importó algo (para avisar en la pantalla de plantillas). */
  alImportar: (cantidad: number) => void;
}

/** Diálogo para asociar plantillas que ya están aprobadas en Meta (sin mandarlas a revisión). */
export function ImportarDesdeMeta({ alCerrar, alImportar }: Props) {
  const qc = useQueryClient();
  const idTitulo = useId();
  const refDialogo = useRef<HTMLDivElement>(null);
  const [elegidas, setElegidas] = useState<Set<string>>(new Set());
  const [importando, setImportando] = useState(false);
  const [errorImportar, setErrorImportar] = useState<string | null>(null);
  const [resultado, setResultado] = useState<ResultadoImportacion[] | null>(null);
  const [totalImportadas, setTotalImportadas] = useState(0);

  const consulta = useQuery({
    queryKey: CLAVE_DE_META,
    queryFn: apiImportarMeta.listar,
    refetchOnMount: "always",
    gcTime: 0,
  });

  useEffect(() => {
    refDialogo.current?.focus();
  }, []);

  const items = consulta.data?.items ?? [];
  const importables = useMemo(() => items.filter(esImportable), [items]);
  const clavesImportables = useMemo(() => new Set(importables.map(claveFila)), [importables]);
  const elegidasVigentes = useMemo(() => [...elegidas].filter((k) => clavesImportables.has(k)), [elegidas, clavesImportables]);
  const todasElegidas = importables.length > 0 && elegidasVigentes.length === importables.length;

  function alternar(p: PlantillaDeMeta) {
    setElegidas((previas) => {
      const sig = new Set(previas);
      const k = claveFila(p);
      if (sig.has(k)) sig.delete(k);
      else sig.add(k);
      return sig;
    });
  }

  function alternarTodas() {
    setElegidas(todasElegidas ? new Set() : new Set(clavesImportables));
  }

  function cerrar() {
    if (totalImportadas > 0) alImportar(totalImportadas);
    alCerrar();
  }

  async function importar() {
    setErrorImportar(null);
    setImportando(true);
    try {
      const pedidas = importables.filter((p) => elegidas.has(claveFila(p))).map((p) => ({ nombre: p.nombre, idioma: p.idioma }));
      const r = await apiImportarMeta.importar(pedidas);
      setResultado(r.items);
      setElegidas(new Set());
      setTotalImportadas((n) => n + r.items.filter((i) => i.resultado === "IMPORTADA").length);
      // La lista local de plantillas y la de Meta (qué ya está importado) se refrescan.
      await qc.invalidateQueries({ queryKey: CLAVES.plantillas });
    } catch (e) {
      setErrorImportar(describirError(e, ti.errorImportar).texto);
    } finally {
      setImportando(false);
    }
  }

  const error = consulta.isError ? describirError(consulta.error, ti.errorMeta) : null;

  return (
    <div className="imp-fondo" onKeyDown={(e) => e.key === "Escape" && cerrar()}>
      <div ref={refDialogo} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={idTitulo} className="imp-dialogo">
        <h2 id={idTitulo}>{ti.titulo}</h2>
        <p className="imp-intro">{ti.intro}</p>

        {consulta.isPending && (
          <p className="imp-estado" role="status">
            {ti.consultando}
          </p>
        )}

        {error && (
          <div role="alert" className="alerta-error">
            <p className="imp-estado">{error.texto}</p>
            {error.noConfigurada ? (
              <Link to="/integraciones/meta">{ti.irConexion}</Link>
            ) : (
              <button type="button" className="btn btn-contorno" onClick={() => void consulta.refetch()}>
                {ti.reintentar}
              </button>
            )}
          </div>
        )}

        {errorImportar && (
          <p className="alerta-error" role="alert">
            {errorImportar}
          </p>
        )}

        {resultado && (
          <>
            <Resumen items={resultado} />
            <div className="imp-acciones">
              <button type="button" className="btn btn-contorno" onClick={() => setResultado(null)}>
                {ti.volverLista}
              </button>
              <button type="button" className="btn btn-primario" onClick={cerrar}>
                {ti.cerrar}
              </button>
            </div>
          </>
        )}

        {!resultado && consulta.data && (
          <>
            {consulta.data.truncado && (
              <p className="alerta-info" role="note">
                {ti.truncado}
              </p>
            )}
            {items.length === 0 ? (
              <p className="not-vacio" role="status">
                {ti.vacio}
              </p>
            ) : (
              <>
                <div className="imp-barra">
                  <label className="imp-todas">
                    <input type="checkbox" checked={todasElegidas} disabled={importables.length === 0 || importando} onChange={alternarTodas} />
                    {ti.seleccionarTodas}
                  </label>
                  <span className="imp-contador" aria-live="polite">
                    {ti.seleccionadas(elegidasVigentes.length)}
                  </span>
                </div>
                <div className="imp-tabla-caja">
                  <table className="imp-tabla" aria-label={ti.tablaAria}>
                    <thead>
                      <tr>
                        <th scope="col">{ti.columnas.seleccion}</th>
                        <th scope="col">{ti.columnas.plantilla}</th>
                        <th scope="col">{ti.columnas.idioma}</th>
                        <th scope="col">{ti.columnas.categoria}</th>
                        <th scope="col">{ti.columnas.estado}</th>
                        <th scope="col">{ti.columnas.importacion}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((p) => (
                        <tr key={claveFila(p)}>
                          <td>
                            {esImportable(p) && (
                              <input
                                type="checkbox"
                                aria-label={ti.seleccionarUna(p.nombre, p.idioma)}
                                checked={elegidas.has(claveFila(p))}
                                disabled={importando}
                                onChange={() => alternar(p)}
                              />
                            )}
                          </td>
                          <td>
                            <div className="imp-nombre">{p.nombre}</div>
                            <p className="imp-texto">{p.texto}</p>
                            <p className="imp-texto">{ti.variables(p.num_variables)}</p>
                            {p.advertencias.map((a) => (
                              <p key={a} className="imp-aviso">
                                {a}
                              </p>
                            ))}
                          </td>
                          <td>{p.idioma}</td>
                          <td>{t.plantillas.categorias[p.categoria] ?? p.categoria}</td>
                          <td>
                            <span className={`insignia not-${CLASE_ESTADO[p.estado_meta] ?? "neutro"}`}>{ti.estadosMeta[p.estado_meta] ?? p.estado_meta}</span>
                          </td>
                          <td>
                            <InsigniasImportacion p={p} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="imp-acciones">
                  <button type="button" className="btn btn-contorno" onClick={cerrar}>
                    {ti.cancelar}
                  </button>
                  <button
                    type="button"
                    className="btn btn-primario"
                    disabled={elegidasVigentes.length === 0 || importando}
                    onClick={() => void importar()}
                  >
                    {importando ? ti.importando : ti.importarSeleccionadas(elegidasVigentes.length)}
                  </button>
                </div>
              </>
            )}
          </>
        )}

        {!resultado && !consulta.data && (
          <div className="imp-acciones">
            <button type="button" className="btn btn-contorno" onClick={cerrar}>
              {ti.cerrar}
            </button>
          </div>
        )}
        {!resultado && consulta.data && items.length === 0 && (
          <div className="imp-acciones">
            <button type="button" className="btn btn-contorno" onClick={cerrar}>
              {ti.cerrar}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
