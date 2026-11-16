import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fechaHora } from "@/shared/fechas";
import { apiNotificaciones, CLAVES, type Notificacion, type Pestana } from "../api";
import { InsigniaEstado } from "../comun";
import { entero, porcentaje } from "../formato";
import { t } from "../textos";
import "../notificaciones.css";

const PESTANAS: Pestana[] = ["envios", "programadas", "borradores"];

function textoAudiencia(n: Notificacion): string {
  if (n.modo === "GRUPO") return n.audiencia_nombre ?? t.nueva.modos.GRUPO;
  if (n.modo === "INDIVIDUAL") return t.listado.individual;
  return t.listado.criterios;
}

function textoDestinatarios(n: Notificacion): string {
  const c = n.contadores;
  if (n.estado === "BORRADOR") return t.listado.sinEnviar;
  if (n.estado === "PROGRAMADA") return t.listado.programados(c.validos);
  if (c.excluidos > 0) return `${c.seleccionados} · ${t.listado.excluidos(c.excluidos)}`;
  return t.listado.deTotal(c.enviados, c.validos);
}

function fechaDe(n: Notificacion): string {
  const iso = n.estado === "PROGRAMADA" ? n.programada_para : n.fecha_envio;
  return iso ? fechaHora(iso) : t.listado.sinFecha;
}

function Indicador({ etiqueta, valor, tono }: { etiqueta: string; valor: string; tono: string }) {
  return (
    <div className="tarjeta not-indicador">
      <span className={`not-icono not-icono-${tono}`} aria-hidden="true" />
      <div>
        <span className="not-indicador-etiqueta">{etiqueta}</span>
        <strong className="not-indicador-valor">{valor}</strong>
      </div>
    </div>
  );
}

/** Listado de notificaciones con indicadores del mes y pestañas (cv1_08). */
export function ListadoNotificaciones() {
  const [pestana, setPestana] = useState<Pestana>("envios");
  const indicadores = useQuery({ queryKey: CLAVES.indicadores, queryFn: apiNotificaciones.indicadores });
  const lista = useQuery({ queryKey: [...CLAVES.listado, pestana], queryFn: () => apiNotificaciones.listar(pestana) });
  // Los conteos de las pestañas salen de la lista (y de los indicadores mientras ésta carga).
  const conteos = lista.data?.conteos ?? indicadores.data?.conteos;

  return (
    <div className="not">
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
        <div className="not-acciones-cabecera">
          <Link to="/notificaciones/plantillas" className="btn btn-contorno not-enlace-boton">
            {t.listado.plantillas}
          </Link>
          <Link to="/notificaciones/nueva" className="btn btn-primario not-enlace-boton">
            {t.listado.nueva}
          </Link>
        </div>
      </div>

      <section className="not-indicadores" aria-label={t.listado.indicadores.aria}>
        {indicadores.data ? (
          <>
            <Indicador etiqueta={t.listado.indicadores.enviadas} valor={entero(indicadores.data.enviadas)} tono="naranja" />
            <Indicador etiqueta={t.listado.indicadores.entregadas} valor={porcentaje(indicadores.data.porcentaje_entregadas)} tono="verde" />
            <Indicador etiqueta={t.listado.indicadores.leidas} valor={porcentaje(indicadores.data.porcentaje_leidas)} tono="azul" />
            <Indicador etiqueta={t.listado.indicadores.fallidas} valor={entero(indicadores.data.fallidas)} tono="rojo" />
          </>
        ) : indicadores.isError ? (
          <p className="alerta-error" role="alert">
            {t.errorCarga}
          </p>
        ) : (
          <p role="status">{t.cargando}</p>
        )}
      </section>

      <div role="tablist" aria-label={t.listado.pestanasAria} className="not-pestanas">
        {PESTANAS.map((p) => (
          <button
            key={p}
            type="button"
            role="tab"
            id={`not-pestana-${p}`}
            aria-selected={pestana === p}
            aria-controls="not-panel"
            className={pestana === p ? "activa" : undefined}
            onClick={() => setPestana(p)}
          >
            {`${t.listado.pestanas[p]}${conteos ? ` (${conteos[p]})` : ""}`}
          </button>
        ))}
      </div>

      <div id="not-panel" role="tabpanel" aria-labelledby={`not-pestana-${pestana}`} className="tarjeta not-tarjeta">
        {lista.isPending && <p role="status" className="not-vacio">{t.cargando}</p>}
        {lista.isError && (
          <p className="alerta-error" role="alert">
            {t.errorCarga}
          </p>
        )}
        {lista.data &&
          (lista.data.items.length === 0 ? (
            <p className="not-vacio">{t.listado.vacio}</p>
          ) : (
            <table className="tabla" aria-label={t.listado.tablaAria}>
              <thead>
                <tr>
                  <th scope="col">{t.listado.columnas.envio}</th>
                  <th scope="col">{t.listado.columnas.audiencia}</th>
                  <th scope="col">{t.listado.columnas.plantilla}</th>
                  <th scope="col">{t.listado.columnas.destinatarios}</th>
                  <th scope="col">{t.listado.columnas.estado}</th>
                  <th scope="col">{t.listado.columnas.fecha}</th>
                  <th scope="col">{t.listado.columnas.accion}</th>
                </tr>
              </thead>
              <tbody>
                {lista.data.items.map((n) => (
                  <tr key={n.id}>
                    <td>
                      <strong>{n.titulo}</strong>
                    </td>
                    <td className="not-suave">{textoAudiencia(n)}</td>
                    <td className="not-plantilla">{n.plantilla?.nombre ?? "—"}</td>
                    <td>{textoDestinatarios(n)}</td>
                    <td>
                      <InsigniaEstado estado={n.estado} />
                    </td>
                    <td className="not-suave">{fechaDe(n)}</td>
                    <td>
                      <Link to={`/notificaciones/${n.id}`} aria-label={`${t.listado.verDetalle}: ${n.titulo}`}>
                        {t.listado.verDetalle}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
      </div>
    </div>
  );
}
