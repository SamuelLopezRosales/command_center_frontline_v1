import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiCampos } from "@/features/campos/api";
import { apiOrganizaciones, apiPlantas } from "@/features/organizaciones/api";
import { fechaHora } from "@/shared/fechas";
import { apiNotificaciones, CLAVES, type Destinatario, type Notificacion } from "../api";
import { BurbujaMensaje, Dialogo, esCodigo, InsigniaEstado, mensajeError } from "../comun";
import { hora } from "../formato";
import { t } from "../textos";
import { construirCatalogo, describirCriterios } from "../nueva/criterios";
import "../notificaciones.css";

const CLASE_DESTINATARIO: Record<string, string> = {
  LEIDO: "info",
  ENTREGADO: "ok",
  RESPONDIO: "proceso",
  FALLIDO: "error",
  ENVIADO: "neutro",
  PENDIENTE: "neutro",
  EXCLUIDO: "neutro",
};

function motivosDeExclusion(items: Destinatario[]): string {
  const cuentas = new Map<string, number>();
  for (const d of items) if (d.estado === "EXCLUIDO" && d.motivo_exclusion) cuentas.set(d.motivo_exclusion, (cuentas.get(d.motivo_exclusion) ?? 0) + 1);
  const partes = [...cuentas].map(([m, n]) => `${n} ${t.motivosExclusion[m] ?? m}`);
  return partes.length > 1 ? `${partes.slice(0, -1).join(", ")} y ${partes[partes.length - 1]}` : (partes[0] ?? "");
}

function Barra({ etiqueta, valor, total, tono }: { etiqueta: string; valor: number; total: number; tono: string }) {
  const ancho = total > 0 ? Math.min(100, Math.round((valor / total) * 100)) : 0;
  return (
    <li className="not-resultado-fila">
      <span className="not-resultado-etiqueta">{etiqueta}</span>
      <div className="not-barra" aria-hidden="true">
        <div className={`not-barra-relleno not-barra-${tono}`} style={{ width: `${ancho}%` }} />
      </div>
      <strong className="not-resultado-valor">{valor}</strong>
    </li>
  );
}

/** Detalle de un envío con destinatarios, reintento de fallidos y duplicado (cv1_10). */
export function DetalleEnvio() {
  const id = Number(useParams().id);
  const navegar = useNavigate();
  const qc = useQueryClient();
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [confirmando, setConfirmando] = useState<"fuera_horario" | "cancelar" | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const detalle = useQuery({
    queryKey: CLAVES.detalle(id),
    queryFn: () => apiNotificaciones.detalle(id),
    enabled: Number.isFinite(id),
    refetchInterval: (q) => (q.state.data?.estado === "ENVIANDO" ? 5000 : false),
  });
  const destinatarios = useQuery({
    queryKey: CLAVES.destinatarios(id),
    queryFn: () => apiNotificaciones.destinatarios(id),
    enabled: Number.isFinite(id),
    refetchInterval: () => (detalle.data?.estado === "ENVIANDO" ? 5000 : false),
  });
  const campos = useQuery({ queryKey: ["notificaciones", "catalogo", "campos"], queryFn: () => apiCampos.listar("activos") });
  const orgs = useQuery({ queryKey: ["notificaciones", "catalogo", "organizaciones"], queryFn: () => apiOrganizaciones.listar(true) });
  const plantas = useQuery({ queryKey: ["notificaciones", "catalogo", "plantas"], queryFn: () => apiPlantas.listar(true) });

  const catalogo = useMemo(
    () =>
      construirCatalogo(
        (orgs.data ?? []).map((o) => ({ id: o.id, nombre: o.razon_social })),
        (plantas.data ?? []).map((p) => ({ id: p.id, nombre: p.nombre })),
        campos.data?.dinamicos ?? [],
      ),
    [orgs.data, plantas.data, campos.data],
  );

  const refrescar = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: CLAVES.detalle(id) }),
      qc.invalidateQueries({ queryKey: CLAVES.destinatarios(id) }),
      qc.invalidateQueries({ queryKey: CLAVES.listado }),
      qc.invalidateQueries({ queryKey: CLAVES.indicadores }),
    ]);
  };

  async function accion(fn: () => Promise<unknown>, exito: string | null, extra: Record<string, string> = {}) {
    setOcupado(true);
    setAviso(null);
    try {
      await fn();
      if (exito) setAviso({ tipo: "ok", texto: exito });
      await refrescar();
    } catch (e) {
      setAviso({ tipo: "error", texto: mensajeError(e, { ...t.detalle.errores, ...extra }) });
    } finally {
      setOcupado(false);
    }
  }

  async function reintentar(confirmarFuera: boolean) {
    setOcupado(true);
    setAviso(null);
    try {
      await apiNotificaciones.reintentar(id, confirmarFuera);
      setConfirmando(null);
      setAviso({ tipo: "ok", texto: t.detalle.reintentado });
      await refrescar();
    } catch (e) {
      if (esCodigo(e, "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION")) setConfirmando("fuera_horario");
      else {
        setConfirmando(null);
        setAviso({ tipo: "error", texto: mensajeError(e, t.detalle.errores) });
      }
    } finally {
      setOcupado(false);
    }
  }

  async function duplicar() {
    setOcupado(true);
    setAviso(null);
    try {
      const copia = await apiNotificaciones.duplicar(id);
      void qc.invalidateQueries({ queryKey: CLAVES.listado });
      navegar(`/notificaciones/${copia.id}/editar`);
    } catch (e) {
      setAviso({ tipo: "error", texto: mensajeError(e, t.detalle.errores) });
    } finally {
      setOcupado(false);
    }
  }

  if (detalle.isPending) return <p role="status">{t.cargando}</p>;
  if (detalle.isError || !detalle.data) {
    return (
      <div className="not">
        <p className="alerta-error" role="alert">
          {mensajeError(detalle.error)}
        </p>
        <Link to="/notificaciones">{t.volver}</Link>
      </div>
    );
  }

  const n: Notificacion = detalle.data;
  const c = n.contadores;
  const items = destinatarios.data?.items ?? [];
  const puedeReintentar = n.estado === "CON_FALLAS" && c.fallidos > 0;
  const puedeCancelar = n.estado === "BORRADOR" || n.estado === "PROGRAMADA";
  const detalleExcluidos = motivosDeExclusion(items);
  const audiencia =
    n.modo === "GRUPO"
      ? [t.detalle.audienciaGrupo(n.audiencia_nombre ?? "—")]
      : n.modo === "INDIVIDUAL"
        ? [t.detalle.audienciaIndividual]
        : describirCriterios(n.criterios, catalogo);
  const referencia = n.fecha_envio ? fechaHora(n.fecha_envio) : null;

  return (
    <div className="not">
      <div className="encabezado">
        <div>
          <h1>{n.titulo}</h1>
          <nav aria-label="Ruta de navegación" className="not-migas">
            <Link to="/notificaciones">{t.migas.notificaciones}</Link> / {referencia ? t.detalle.migas(referencia) : t.detalle.migasSinEnvio}{" "}
            <InsigniaEstado estado={n.estado} />
          </nav>
        </div>
        <div className="not-acciones-cabecera">
          {n.estado === "BORRADOR" && (
            <Link to={`/notificaciones/${n.id}/editar`} className="btn btn-contorno not-enlace-boton">
              {t.detalle.editarBorrador}
            </Link>
          )}
          {puedeCancelar && (
            <button type="button" className="btn btn-peligro" disabled={ocupado} onClick={() => setConfirmando("cancelar")}>
              {t.detalle.cancelar}
            </button>
          )}
          <button type="button" className="btn btn-contorno" disabled={ocupado} onClick={() => void duplicar()}>
            {t.detalle.duplicar}
          </button>
          {puedeReintentar && (
            <button type="button" className="btn btn-primario" disabled={ocupado} onClick={() => void reintentar(false)}>
              {t.detalle.reintentar(c.fallidos)}
            </button>
          )}
        </div>
      </div>

      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}
      {n.estado === "PROGRAMADA" && n.programada_para && <p className="alerta-info">{t.detalle.programadaPara(fechaHora(n.programada_para))}</p>}
      {n.motivo_cancelacion && <p className="alerta-info">{n.motivo_cancelacion}</p>}

      <div className="not-detalle">
        <div className="not-columna">
          <section className="tarjeta not-seccion" aria-labelledby="not-resultado">
            <h2 id="not-resultado">{t.detalle.resultado}</h2>
            <ul className="not-resultado">
              <Barra etiqueta={t.detalle.seleccionados} valor={c.seleccionados} total={c.seleccionados} tono="azul" />
              <Barra etiqueta={t.detalle.enviados} valor={c.enviados} total={c.seleccionados} tono="verde" />
              <Barra etiqueta={t.detalle.entregados} valor={c.entregados} total={c.seleccionados} tono="verde" />
              <Barra etiqueta={t.detalle.leidos} valor={c.leidos} total={c.seleccionados} tono="naranja" />
              <Barra etiqueta={t.detalle.fallidos} valor={c.fallidos} total={c.seleccionados} tono="rojo" />
            </ul>
            {c.excluidos > 0 && (
              <p className="not-excluidos-texto">
                {t.detalle.excluidosAntes(c.excluidos)}
                {detalleExcluidos ? `: ${detalleExcluidos}.` : "."}
              </p>
            )}
          </section>

          <section className="tarjeta not-tarjeta" aria-label={t.detalle.destinatariosAria}>
            {destinatarios.isPending && <p role="status" className="not-vacio">{t.cargando}</p>}
            {destinatarios.isError && (
              <p className="alerta-error" role="alert">
                {t.errorCarga}
              </p>
            )}
            {destinatarios.data &&
              (items.length === 0 ? (
                <p className="not-vacio">{t.detalle.sinDestinatarios}</p>
              ) : (
                <table className="tabla" aria-label={t.detalle.destinatariosAria}>
                  <thead>
                    <tr>
                      <th scope="col">{t.detalle.columnas.nombre}</th>
                      <th scope="col">{t.detalle.columnas.planta}</th>
                      <th scope="col">{t.detalle.columnas.celular}</th>
                      <th scope="col">{t.detalle.columnas.estado}</th>
                      <th scope="col">{t.detalle.columnas.hora}</th>
                      <th scope="col">{t.detalle.columnas.accion}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((d) => (
                      <tr key={d.id}>
                        <td>{d.nombre}</td>
                        <td className="not-suave">{d.planta ?? "—"}</td>
                        <td className="not-suave">{d.celular_enmascarado ?? "—"}</td>
                        <td>
                          <span className={`insignia not-${CLASE_DESTINATARIO[d.estado] ?? "neutro"}`}>{t.estadosDestinatario[d.estado] ?? d.estado}</span>
                        </td>
                        <td className="not-suave">{hora(d.fecha_estado)}</td>
                        <td>
                          {d.estado === "LEIDO" || d.estado === "RESPONDIO" ? (
                            <Link to="/chat" aria-label={`${t.detalle.verChat}: ${d.nombre}`}>
                              {t.detalle.verChat}
                            </Link>
                          ) : d.estado === "FALLIDO" && d.motivo_fallo ? (
                            <span className="not-rechazo" title={t.detalle.motivoFallo}>
                              {t.detalle.motivosFallo[d.motivo_fallo] ?? d.motivo_fallo}
                            </span>
                          ) : d.estado === "EXCLUIDO" && d.motivo_exclusion ? (
                            <span className="not-suave">{t.motivosExclusion[d.motivo_exclusion] ?? d.motivo_exclusion}</span>
                          ) : (
                            t.detalle.sinAccion
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
          </section>
        </div>

        <aside className="not-columna">
          <section className="tarjeta not-seccion" aria-labelledby="not-mensaje-enviado">
            <h2 id="not-mensaje-enviado">{t.detalle.mensaje}</h2>
            {n.vista_previa && <BurbujaMensaje texto={n.vista_previa} />}
            {n.plantilla && (
              <p className="not-suave not-plantilla-linea">
                {t.detalle.plantillaMeta(n.plantilla.nombre, (t.plantillas.estados[n.plantilla.estado_meta] ?? n.plantilla.estado_meta).toUpperCase())}
              </p>
            )}
            {c.respondieron > 0 && (
              <>
                <p>
                  <strong>{t.detalle.respuestas(c.respondieron)}</strong>
                </p>
                <Link to="/chat">{t.detalle.verConversaciones}</Link>
              </>
            )}
          </section>

          <section className="tarjeta not-seccion" aria-labelledby="not-audiencia">
            <h2 id="not-audiencia">{t.detalle.audiencia}</h2>
            <ul className="not-fichas">
              {audiencia.map((a) => (
                <li key={a} className="not-ficha">
                  {a}
                </li>
              ))}
              <li className="not-ficha not-ficha-azul">{t.detalle.audienciaConsentimiento}</li>
            </ul>
          </section>

          <section className="tarjeta not-seccion" aria-labelledby="not-linea">
            <h2 id="not-linea">{t.detalle.lineaTiempo}</h2>
            <ol className="not-linea">
              {n.linea_de_tiempo.map((h) => (
                <li key={`${h.evento}-${h.en}`}>
                  <span className="not-linea-hora">{h.evento === "PROGRAMADA_PARA" ? fechaHora(h.en) : hora(h.en)}</span>
                  <span>{h.evento === "ENVIADA" ? `${t.detalle.hitos.ENVIADA}: ${c.enviados}/${c.validos}` : (t.detalle.hitos[h.evento] ?? h.evento)}</span>
                </li>
              ))}
            </ol>
          </section>
        </aside>
      </div>

      {confirmando === "fuera_horario" && (
        <Dialogo
          titulo={t.detalle.reintentarTitulo}
          alCerrar={() => setConfirmando(null)}
          acciones={
            <>
              <button type="button" className="btn btn-contorno" onClick={() => setConfirmando(null)}>
                {t.cancelar}
              </button>
              <button type="button" className="btn btn-primario" disabled={ocupado} onClick={() => void reintentar(true)}>
                {t.detalle.reintentarFueraHorarioConfirmar}
              </button>
            </>
          }
        >
          <p>{t.detalle.reintentarFueraHorario}</p>
        </Dialogo>
      )}
      {confirmando === "cancelar" && (
        <Dialogo
          titulo={t.detalle.cancelarTitulo}
          alCerrar={() => setConfirmando(null)}
          acciones={
            <>
              <button type="button" className="btn btn-contorno" onClick={() => setConfirmando(null)}>
                {t.cerrar}
              </button>
              <button
                type="button"
                className="btn btn-peligro"
                disabled={ocupado}
                onClick={() => {
                  setConfirmando(null);
                  void accion(() => apiNotificaciones.cancelar(id), t.detalle.cancelado);
                }}
              >
                {t.detalle.cancelarConfirmar}
              </button>
            </>
          }
        >
          <p>{t.detalle.cancelarTexto}</p>
        </Dialogo>
      )}
    </div>
  );
}
