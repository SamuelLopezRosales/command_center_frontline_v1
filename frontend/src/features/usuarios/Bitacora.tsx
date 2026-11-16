import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi } from "@/shared/errores";
import { fechaHora } from "@/shared/fechas";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { consultarBitacora, listarUsuarios, type FiltroBitacora } from "./api";
import { ACCIONES_BITACORA, t } from "./textos";
import "./usuarios.css";

const LIMITE = 20;
// México no tiene horario de verano desde 2022: el día civil local es UTC-6.
const inicioDelDia = (d: string) => new Date(`${d}T00:00:00-06:00`).toISOString();
const finDelDia = (d: string) => new Date(`${d}T23:59:59.999-06:00`).toISOString();

/** Consulta de la bitácora de auditoría (DSH-05) con filtros y paginación por cursor. */
export function Bitacora() {
  const { estado, tiene } = useSesion();
  const puede = tiene("bitacora:ver");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [accion, setAccion] = useState("");
  const [usuarioId, setUsuarioId] = useState("");
  const [orden, setOrden] = useState<"asc" | "desc">("desc");
  const [cursores, setCursores] = useState<(string | undefined)[]>([undefined]);

  const filtro: FiltroBitacora = {
    desde: desde ? inicioDelDia(desde) : undefined,
    hasta: hasta ? finDelDia(hasta) : undefined,
    usuario_id: usuarioId ? Number(usuarioId) : undefined,
    accion: accion || undefined,
    orden,
    cursor: cursores.at(-1),
    limite: LIMITE,
  };

  const registros = useQuery({
    queryKey: ["usuarios", "bitacora", filtro],
    queryFn: () => consultarBitacora(filtro),
    placeholderData: (previo) => previo,
    enabled: puede,
  });
  const usuarios = useQuery({ queryKey: ["usuarios", "lista"], queryFn: listarUsuarios, enabled: puede && tiene("usuarios:administrar") });

  if (estado === "cargando") return <p role="status">{t.cargando}</p>;
  if (!puede)
    return (
      <div className="usr">
        <h1>{t.bitacoraPantalla.titulo}</h1>
        <p className="alerta-error" role="alert">
          {t.bitacoraPantalla.sinPermiso}
        </p>
      </div>
    );

  const cambiar = (fn: () => void) => {
    fn();
    setCursores([undefined]);
  };
  const datos = registros.data;

  return (
    <div className="usr">
      <div className="encabezado">
        <div>
          <h1>{t.bitacoraPantalla.titulo}</h1>
          <p>{t.bitacoraPantalla.subtitulo}</p>
        </div>
        {tiene("usuarios:administrar") && (
          <Link className="btn btn-contorno usr-enlace-boton" to="/usuarios">
            {t.bitacoraPantalla.volver}
          </Link>
        )}
      </div>

      <form className="usr-filtros" role="search" aria-label={t.bitacoraPantalla.filtros} onSubmit={(e) => e.preventDefault()}>
        <input type="date" aria-label={t.bitacoraPantalla.desde} value={desde} onChange={(e) => cambiar(() => setDesde(e.target.value))} />
        <input type="date" aria-label={t.bitacoraPantalla.hasta} value={hasta} onChange={(e) => cambiar(() => setHasta(e.target.value))} />
        <select aria-label={t.bitacoraPantalla.accion} value={accion} onChange={(e) => cambiar(() => setAccion(e.target.value))}>
          <option value="">{t.bitacoraPantalla.todasAcciones}</option>
          {Object.entries(ACCIONES_BITACORA).map(([codigo, etiqueta]) => (
            <option key={codigo} value={codigo}>
              {etiqueta}
            </option>
          ))}
        </select>
        {usuarios.data && (
          <select aria-label={t.bitacoraPantalla.usuario} value={usuarioId} onChange={(e) => cambiar(() => setUsuarioId(e.target.value))}>
            <option value="">{t.bitacoraPantalla.todosUsuarios}</option>
            {usuarios.data.map((u) => (
              <option key={u.id} value={u.id}>
                {u.nombre}
              </option>
            ))}
          </select>
        )}
        <select aria-label={t.bitacoraPantalla.orden} value={orden} onChange={(e) => cambiar(() => setOrden(e.target.value as "asc" | "desc"))}>
          <option value="desc">{t.bitacoraPantalla.recientesPrimero}</option>
          <option value="asc">{t.bitacoraPantalla.antiguosPrimero}</option>
        </select>
      </form>

      {registros.isPending && <p role="status">{t.cargando}</p>}
      {registros.isError && (
        <p className="alerta-error" role="alert">
          {registros.error instanceof ErrorApi && registros.error.codigo === "ACCION_DESCONOCIDA" ? t.bitacoraPantalla.errorAccion : t.errorCarga}
        </p>
      )}
      {datos && (
        <div className="tarjeta usr-tarjeta">
          {datos.items.length === 0 ? (
            <p className="usr-vacio">{t.bitacoraPantalla.vacio}</p>
          ) : (
            <table className="tabla" aria-label={t.bitacoraPantalla.tablaAria}>
              <thead>
                <tr>
                  <th scope="col">{t.bitacoraPantalla.columnas.fecha}</th>
                  <th scope="col">{t.bitacoraPantalla.columnas.usuario}</th>
                  <th scope="col">{t.bitacoraPantalla.columnas.accion}</th>
                  <th scope="col">{t.bitacoraPantalla.columnas.entidad}</th>
                  <th scope="col">{t.bitacoraPantalla.columnas.origen}</th>
                  <th scope="col">{t.bitacoraPantalla.columnas.ip}</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((r) => (
                  <tr key={r.id}>
                    <td className="usr-suave">{fechaHora(r.fecha_hora)}</td>
                    <td>{r.usuario_nombre ?? t.bitacoraPantalla.sistema}</td>
                    <td>{ACCIONES_BITACORA[r.accion] ?? r.accion}</td>
                    <td className="usr-suave">{r.entidad_id ? `${r.entidad} #${r.entidad_id}` : r.entidad}</td>
                    <td className="usr-suave">{r.origen}</td>
                    <td className="usr-suave">{r.ip ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="usr-pie">
            <span className="usr-suave">{datos.items.length > 0 ? t.bitacoraPantalla.mostrando(datos.items.length) : ""}</span>
            <span>
              <button type="button" className="btn btn-contorno" disabled={cursores.length <= 1} onClick={() => setCursores((c) => c.slice(0, -1))}>
                {t.bitacoraPantalla.anterior}
              </button>{" "}
              <button type="button" className="btn btn-contorno" disabled={!datos.siguiente} onClick={() => setCursores((c) => [...c, datos.siguiente ?? undefined])}>
                {t.bitacoraPantalla.siguiente}
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
