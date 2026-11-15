import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { mensajeDeError } from "@/shared/errores";
import { fechaHora } from "@/shared/fechas";
import { listarHistorial, listarPlantillas, reenviarConstancia, urlDeDescarga } from "../api";
import { Pestanas } from "../Pestanas";
import { t } from "../textos";
import "../constancias.css";
import type { EstadoEntrega, FiltroHistorial, ItemHistorial } from "./tipos";

const LIMITE = 20;
const CLASE_ESTADO: Record<EstadoEntrega, string> = { ENTREGADA: "ok", FALLIDA: "error", PENDIENTE: "proceso" };
const ESTADOS: EstadoEntrega[] = ["ENTREGADA", "FALLIDA", "PENDIENTE"];

/**
 * Acciones permitidas por estado (CC-REQ-088 y 089):
 * - la descarga no se ofrece con PENDIENTE (la API responde 409);
 * - el reenvío solo existe con FALLIDA.
 */
export function accionesDe(estado: EstadoEntrega): { descargar: boolean; reenviar: boolean } {
  return { descargar: estado !== "PENDIENTE", reenviar: estado === "FALLIDA" };
}

function Fila({ item, alAviso }: { item: ItemHistorial; alAviso: (a: { tipo: "ok" | "error"; texto: string } | null) => void }) {
  const [ocupado, setOcupado] = useState(false);
  const acciones = accionesDe(item.estado_entrega);

  async function descargar() {
    setOcupado(true);
    alAviso(null);
    try {
      const { url } = await urlDeDescarga(item.id);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      alAviso({ tipo: "error", texto: mensajeDeError(e) || t.historial.errorDescarga });
    } finally {
      setOcupado(false);
    }
  }

  async function reenviar() {
    setOcupado(true);
    alAviso(null);
    try {
      await reenviarConstancia(item.id);
      alAviso({ tipo: "ok", texto: t.historial.reenviada(item.folio) });
    } catch (e) {
      alAviso({ tipo: "error", texto: mensajeDeError(e) || t.historial.errorReenvio });
    } finally {
      setOcupado(false);
    }
  }

  return (
    <tr>
      <td>{item.folio}</td>
      <td className="cons-suave">{item.colaborador_nombre}</td>
      <td className="cons-suave">{item.plantilla_nombre}</td>
      <td>
        <span className="cons-version">{`v${item.version}`}</span>
      </td>
      <td className="cons-suave">{fechaHora(item.fecha)}</td>
      <td>
        <span className="insignia neutro">{t.historial.canales[item.canal] ?? item.canal}</span>
      </td>
      <td>
        <span className={`insignia ${CLASE_ESTADO[item.estado_entrega] ?? "neutro"}`}>
          {t.historial.estados[item.estado_entrega] ?? item.estado_entrega}
        </span>
      </td>
      <td className="cons-acciones">
        {acciones.descargar && (
          <button type="button" className="btn-enlace" disabled={ocupado} aria-label={`${t.historial.descargar} ${item.folio}`} onClick={() => void descargar()}>
            {t.historial.descargar}
          </button>
        )}
        {acciones.reenviar && (
          <button type="button" className="btn-enlace cons-peligro" disabled={ocupado} aria-label={`${t.historial.reenviar} ${item.folio}`} onClick={() => void reenviar()}>
            {t.historial.reenviar}
          </button>
        )}
      </td>
    </tr>
  );
}

/** Historial de constancias generadas (cv1_07). El endpoint DSH-11 llega con T-213. */
export function HistorialConstancias() {
  const [busqueda, setBusqueda] = useState("");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [plantillaId, setPlantillaId] = useState("");
  const [estado, setEstado] = useState<"" | EstadoEntrega>("");
  const [pagina, setPagina] = useState(1);
  const [q, setQ] = useState("");
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);

  // El texto se aplica con una pausa para no consultar en cada tecla.
  useEffect(() => {
    const espera = setTimeout(() => {
      setQ(busqueda.trim());
      setPagina(1);
    }, 300);
    return () => clearTimeout(espera);
  }, [busqueda]);

  const filtro: FiltroHistorial = {
    q: q || undefined,
    desde: desde || undefined,
    hasta: hasta || undefined,
    plantilla_id: plantillaId ? Number(plantillaId) : undefined,
    estado: estado || undefined,
    pagina,
    limite: LIMITE,
  };

  const plantillas = useQuery({ queryKey: ["constancias", "plantillas"], queryFn: listarPlantillas });
  const historial = useQuery({
    queryKey: ["constancias", "historial", filtro],
    queryFn: () => listarHistorial(filtro),
    placeholderData: (previo) => previo,
  });

  const cambiar = (fn: () => void) => {
    fn();
    setPagina(1);
  };
  const datos = historial.data;
  const primero = datos && datos.total > 0 ? (datos.pagina - 1) * datos.limite + 1 : 0;
  const ultimo = datos ? Math.min(datos.total, (datos.pagina - 1) * datos.limite + datos.items.length) : 0;

  return (
    <div className="cons">
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtituloHistorial}</p>
        </div>
      </div>
      <Pestanas />

      <form className="cons-filtros" role="search" onSubmit={(e) => e.preventDefault()}>
        <input type="search" aria-label={t.historial.buscar} placeholder={t.historial.buscar} value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
        <input type="date" aria-label={t.historial.desde} value={desde} onChange={(e) => cambiar(() => setDesde(e.target.value))} />
        <input type="date" aria-label={t.historial.hasta} value={hasta} onChange={(e) => cambiar(() => setHasta(e.target.value))} />
        <select aria-label={t.historial.plantilla} value={plantillaId} onChange={(e) => cambiar(() => setPlantillaId(e.target.value))}>
          <option value="">{t.historial.todasPlantillas}</option>
          {plantillas.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.nombre}
            </option>
          ))}
        </select>
        <select aria-label={t.historial.estado} value={estado} onChange={(e) => cambiar(() => setEstado(e.target.value as "" | EstadoEntrega))}>
          <option value="">{t.historial.todosEstados}</option>
          {ESTADOS.map((s) => (
            <option key={s} value={s}>
              {t.historial.estados[s]}
            </option>
          ))}
        </select>
      </form>

      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}
      {historial.isPending && <p role="status">{t.cargando}</p>}
      {historial.isError && (
        <p className="alerta-error" role="alert">
          {t.errorCarga}
        </p>
      )}
      {datos && (
        <div className="tarjeta cons-tarjeta">
          {datos.items.length === 0 ? (
            <p className="cons-vacio">{t.historial.vacio}</p>
          ) : (
            <table className="tabla" aria-label={t.historial.tablaAria}>
              <thead>
                <tr>
                  <th scope="col">{t.historial.columnas.folio}</th>
                  <th scope="col">{t.historial.columnas.colaborador}</th>
                  <th scope="col">{t.historial.columnas.plantilla}</th>
                  <th scope="col">{t.historial.columnas.version}</th>
                  <th scope="col">{t.historial.columnas.fecha}</th>
                  <th scope="col">{t.historial.columnas.canal}</th>
                  <th scope="col">{t.historial.columnas.estado}</th>
                  <th scope="col">{t.historial.columnas.accion}</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((i) => (
                  <Fila key={i.id} item={i} alAviso={setAviso} />
                ))}
              </tbody>
            </table>
          )}
          <div className="cons-pie">
            <span className="cons-suave">{datos.total > 0 ? t.historial.mostrando(primero, ultimo, datos.total) : t.historial.sinConstancias}</span>
            <span>
              <button type="button" className="btn btn-contorno" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
                {t.historial.anterior}
              </button>{" "}
              <button type="button" className="btn btn-contorno" disabled={ultimo >= datos.total} onClick={() => setPagina((p) => p + 1)}>
                {t.historial.siguiente}
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
