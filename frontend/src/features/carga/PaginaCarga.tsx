import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { subirAS3 } from "@/features/organizaciones/api";
import { mensajeDeError } from "@/shared/errores";
import { fechaHora } from "@/shared/fechas";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { CLAVE_CARGAS, LIMITE_ARCHIVO, RUTA_PLANTILLA, apiCargas } from "./api";
import "./carga.css";
import { descargarArchivo } from "./descargas";
import { textos as t } from "./textos";

export function claseEstadoCarga(estado: string): string {
  return estado === "TERMINADA" ? "ok" : estado === "EN_PROCESO" ? "proceso" : "neutro";
}

export function PaginaCarga() {
  const navegar = useNavigate();
  const cliente = useQueryClient();
  const { auth } = useSesion();
  const [archivo, setArchivo] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const [pagina, setPagina] = useState(1);
  const historial = useQuery({ queryKey: [...CLAVE_CARGAS, "lista", pagina], queryFn: () => apiCargas.listar(pagina) });

  async function bajarPlantilla() {
    setError(null);
    try {
      await descargarArchivo(RUTA_PLANTILLA, "plantilla_colaboradores.xlsx", await auth.token());
    } catch (e) {
      setError(mensajeDeError(e));
    }
  }

  function elegir(f: File | null) {
    setError(null);
    if (f && !f.name.toLowerCase().endsWith(".xlsx")) {
      setArchivo(null);
      return setError(t.soloXlsx);
    }
    if (f && f.size > LIMITE_ARCHIVO) {
      setArchivo(null);
      return setError(t.demasiadoGrande);
    }
    setArchivo(f);
  }

  async function subir() {
    if (!archivo) return setError(t.archivoVacio);
    setSubiendo(true);
    setError(null);
    try {
      // 1) La API crea la carga y entrega una URL firmada; 2) el archivo va directo a S3; 3) se confirma.
      const inicio = await apiCargas.iniciar(archivo.name, archivo.size);
      await subirAS3(inicio.url_subida, archivo, inicio.content_type);
      await apiCargas.confirmar(inicio.carga_id);
      await cliente.invalidateQueries({ queryKey: CLAVE_CARGAS });
      navegar(`/cargas/${inicio.carga_id}`);
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setSubiendo(false);
    }
  }

  const datos = historial.data;
  const paginas = datos ? Math.max(1, Math.ceil(datos.total / datos.limite)) : 1;

  return (
    <>
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
        <Link className="btn btn-contorno" to="/colaboradores">
          {t.volver}
        </Link>
      </div>

      {error && (
        <div className="alerta-error" role="alert">
          {error}
        </div>
      )}

      <div className="car-pasos">
        <section className="tarjeta" aria-labelledby="car-p1">
          <h2 id="car-p1">{t.paso1}</h2>
          <p>{t.paso1Texto}</p>
          <button className="btn btn-contorno" onClick={() => void bajarPlantilla()}>
            {t.descargarPlantilla}
          </button>
        </section>
        <section className="tarjeta" aria-labelledby="car-p2">
          <h2 id="car-p2">{t.paso2}</h2>
          <p>{t.paso2Texto}</p>
          <div className="campo">
            <label htmlFor="car-archivo">{t.archivo}</label>
            <input
              id="car-archivo"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => elegir(e.target.files?.[0] ?? null)}
            />
          </div>
          <button className="btn btn-primario" disabled={subiendo} onClick={() => void subir()}>
            {subiendo ? t.subiendo : t.subir}
          </button>
        </section>
      </div>

      <section className="tarjeta car-tabla" aria-labelledby="car-hist">
        <h2 id="car-hist">{t.historial}</h2>
        {historial.isPending && <p role="status" style={{ padding: "0 24px" }}>{t.cargando}</p>}
        {historial.isError && (
          <div className="alerta-error" role="alert" style={{ margin: 16 }}>
            {t.errorCarga}{" "}
            <button className="btn-enlace" onClick={() => void historial.refetch()}>
              {t.reintentar}
            </button>
          </div>
        )}
        {datos && (
          <>
            <table className="tabla">
              <thead>
                <tr>
                  <th>{t.columnas.fecha}</th>
                  <th>{t.columnas.archivo}</th>
                  <th>{t.columnas.estado}</th>
                  <th>{t.columnas.correctas}</th>
                  <th>{t.columnas.errores}</th>
                  <th>{t.columnas.accion}</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((c) => (
                  <tr key={c.id}>
                    <td>{fechaHora(c.fecha_carga)}</td>
                    <td>{c.nombre_archivo}</td>
                    <td>
                      <span className={`insignia ${claseEstadoCarga(c.estado)}`}>{t.estados[c.estado] ?? c.estado}</span>
                    </td>
                    <td>{c.filas_ok}</td>
                    <td>{c.filas_error}</td>
                    <td>
                      <Link to={`/cargas/${c.id}`} aria-label={`${t.ver} carga ${c.id}`}>
                        {t.ver}
                      </Link>
                    </td>
                  </tr>
                ))}
                {datos.items.length === 0 && (
                  <tr>
                    <td colSpan={6}>{t.sinCargas}</td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="car-pie">
              <span>{t.detalle.pagina(pagina, paginas)}</span>
              <button className="btn btn-contorno" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
                {t.anterior}
              </button>
              <button className="btn btn-contorno" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
                {t.siguiente}
              </button>
            </div>
          </>
        )}
      </section>
    </>
  );
}
