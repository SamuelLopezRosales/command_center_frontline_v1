import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { fechaHora } from "@/shared/fechas";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { apiDashboard } from "./api";
import "./dashboard.css";
import { textos as t } from "./textos";

function claseEstado(estado: string): string {
  const e = estado.toUpperCase();
  if (/FALL|ERROR|RECHAZ/.test(e)) return "error";
  if (/ENTREGAD|COMPLETAD|GENERAD|OK/.test(e)) return "ok";
  if (/PROCES|PENDIENT|ENVIAD|COLA/.test(e)) return "proceso";
  return "neutro";
}

function Estado({ valor }: { valor: string }) {
  return <span className={`insignia ${claseEstado(valor)}`}>{valor.replace(/_/g, " ")}</span>;
}

interface ConsultaLista<T> {
  isPending: boolean;
  isError: boolean;
  data: T[] | undefined;
  refetch: () => unknown;
}

function Seccion<T>({ consulta, vacio, hijos }: { consulta: ConsultaLista<T>; vacio: string; hijos: (datos: T[]) => ReactNode }) {
  if (consulta.isPending) return <p role="status">{t.cargando}</p>;
  if (consulta.isError)
    return (
      <div className="alerta-error" role="alert">
        {t.error}{" "}
        <button className="btn-enlace" onClick={() => void consulta.refetch()}>
          {t.reintentar}
        </button>
      </div>
    );
  if (!consulta.data || consulta.data.length === 0) return <p className="dsh-ayuda">{vacio}</p>;
  return <>{hijos(consulta.data)}</>;
}

export function Dashboard() {
  const { usuario } = useSesion();
  const resumen = useQuery({ queryKey: ["dashboard", "resumen"], queryFn: apiDashboard.resumen });
  const solicitudes = useQuery({ queryKey: ["dashboard", "solicitudes"], queryFn: () => apiDashboard.solicitudes() });
  const constancias = useQuery({ queryKey: ["dashboard", "constancias"], queryFn: () => apiDashboard.constancias() });
  const alertas = useQuery({ queryKey: ["dashboard", "alertas"], queryFn: apiDashboard.alertas });
  const r = resumen.data;

  const tarjetas = [
    { clave: "activos", color: "verde", etiqueta: t.tarjetas.activos, valor: r?.colaboradores_activos },
    { clave: "mes", color: "naranja", etiqueta: t.tarjetas.constanciasMes, valor: r?.constancias_mes },
    { clave: "proceso", color: "ambar", etiqueta: t.tarjetas.enProceso, valor: r?.solicitudes_en_proceso },
    { clave: "plantillas", color: "azul", etiqueta: t.tarjetas.plantillas, valor: r?.plantillas_activas },
  ];

  return (
    <>
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          {usuario && <p>{t.bienvenida(usuario.nombre)}</p>}
        </div>
        <Link className="btn btn-contorno" to="/constancias/historial">
          {t.verHistorial}
        </Link>
      </div>

      {r?.vacio && (
        <div className="alerta-info dsh-vacio" role="status">
          {t.vacio} <Link to="/colaboradores">{t.vacioColaboradores}</Link>
        </div>
      )}
      {resumen.isError && (
        <div className="alerta-error" role="alert">
          {t.error}{" "}
          <button className="btn-enlace" onClick={() => void resumen.refetch()}>
            {t.reintentar}
          </button>
        </div>
      )}

      <section className="dsh-tarjetas" aria-label="Indicadores">
        {tarjetas.map((x) => (
          <div key={x.clave} className="tarjeta dsh-tarjeta" data-testid={`tarjeta-${x.clave}`}>
            <div className={`dsh-icono ${x.color}`} aria-hidden="true">
              <span />
            </div>
            <div>
              <div className="dsh-etiqueta">{x.etiqueta}</div>
              <div className="dsh-cifra">{x.valor ?? "—"}</div>
            </div>
          </div>
        ))}
      </section>

      <div className="dsh-fila">
        <section className="tarjeta" aria-labelledby="dsh-sol">
          <h2 id="dsh-sol">{t.solicitudes}</h2>
          <Seccion
            consulta={solicitudes}
            vacio={t.sinSolicitudes}
            hijos={(items) => (
              <ul className="dsh-lista">
                {items.map((s) => (
                  <li key={s.id} className="dsh-item">
                    <div>
                      <strong>{s.colaborador_nombre}</strong>
                      <small>
                        {s.plantilla_nombre} · v{s.version}
                      </small>
                    </div>
                    <Estado valor={s.estado} />
                  </li>
                ))}
              </ul>
            )}
          />
        </section>

        <section className="tarjeta" aria-labelledby="dsh-ale">
          <h2 id="dsh-ale">{t.alertas}</h2>
          <Seccion
            consulta={alertas}
            vacio={t.sinAlertas}
            hijos={(items) => (
              <ul className="dsh-lista">
                {items.map((a) => (
                  <li key={a.tipo} className="dsh-item">
                    <div className="dsh-alerta">
                      <span className={`dsh-punto${a.tipo === "CONSTANCIA_FALLIDA" ? " rojo" : ""}`} aria-hidden="true" />
                      <div>
                        <strong>{a.titulo}</strong>
                        <small>{a.detalle}</small>
                      </div>
                    </div>
                    <Link className="dsh-revisar" to={a.enlace} aria-label={`${t.revisar}: ${a.titulo}`}>
                      {t.revisar}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          />
        </section>
      </div>

      <section className="tarjeta dsh-tabla" aria-labelledby="dsh-con">
        <h2 id="dsh-con">{t.constancias}</h2>
        <Seccion
          consulta={constancias}
          vacio={t.sinConstancias}
          hijos={(items) => (
            <table className="tabla">
              <thead>
                <tr>
                  <th>{t.columnas.folio}</th>
                  <th>{t.columnas.colaborador}</th>
                  <th>{t.columnas.plantilla}</th>
                  <th>{t.columnas.fecha}</th>
                  <th>{t.columnas.estado}</th>
                  <th>{t.columnas.accion}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.folio}>
                    <td>{c.folio}</td>
                    <td>{c.colaborador_nombre}</td>
                    <td>
                      {c.plantilla_nombre} v{c.version}
                    </td>
                    <td>{fechaHora(c.fecha)}</td>
                    <td>
                      <Estado valor={c.estado_entrega} />
                    </td>
                    <td>
                      <Link to={`/constancias/historial?q=${encodeURIComponent(c.folio)}`} aria-label={`${t.descargar} ${c.folio}`}>
                        {t.descargar}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        />
      </section>
    </>
  );
}
