import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import { aplicarErroresDeCampo, mensajeDeError } from "@/shared/errores";
import { Campo } from "@/shared/ui/Campo";
import {
  actualizarPlantilla,
  crearPlantilla,
  duplicarPlantilla,
  eliminarPlantilla,
  listarPlantillas,
  type Plantilla,
} from "../api";
import { Dialogo } from "../Dialogo";
import { fechaMedia } from "../formato";
import { Pestanas } from "../Pestanas";
import { t } from "../textos";
import "../constancias.css";

const CLASE_ESTADO: Record<string, string> = { ACTIVA: "ok", BORRADOR: "proceso", INACTIVA: "neutro" };

const esquema = z.object({
  nombre: z.string().trim().min(1, t.listado.nombreRequerido).max(120, t.listado.nombreLargo),
  descripcion: z.string().trim().max(500).optional(),
});
type Entrada = z.infer<typeof esquema>;

function NuevaPlantilla({ alCerrar }: { alCerrar: () => void }) {
  const navegar = useNavigate();
  const qc = useQueryClient();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const { register, handleSubmit, setError, formState } = useForm<Entrada>({ resolver: zodResolver(esquema) });

  const enviar = handleSubmit(async (v) => {
    setErrorGeneral(null);
    try {
      const creada = await crearPlantilla({ nombre: v.nombre, descripcion: v.descripcion || null });
      void qc.invalidateQueries({ queryKey: ["constancias", "plantillas"] });
      navegar(`/constancias/${creada.id}`);
    } catch (e) {
      if (!aplicarErroresDeCampo(e, setError)) setErrorGeneral(mensajeDeError(e));
    }
  });

  return (
    <Dialogo
      titulo={t.listado.nuevaTitulo}
      alCerrar={alCerrar}
      acciones={
        <>
          <button type="button" className="btn btn-contorno" onClick={alCerrar}>
            {t.listado.cancelar}
          </button>
          <button type="submit" form="cons-form-nueva" className="btn btn-primario" disabled={formState.isSubmitting}>
            {t.listado.crear}
          </button>
        </>
      }
    >
      <form id="cons-form-nueva" onSubmit={(e) => void enviar(e)} noValidate>
        {errorGeneral && (
          <p className="alerta-error" role="alert">
            {errorGeneral}
          </p>
        )}
        <Campo etiqueta={t.listado.nombre} error={formState.errors.nombre?.message} {...register("nombre")} />
        <Campo etiqueta={t.listado.descripcion} error={formState.errors.descripcion?.message} {...register("descripcion")} />
      </form>
    </Dialogo>
  );
}

/** Listado de plantillas con estado, versión y acciones (cv1_05). */
export function ListadoPlantillas() {
  const qc = useQueryClient();
  const plantillas = useQuery({ queryKey: ["constancias", "plantillas"], queryFn: listarPlantillas });
  const [creando, setCreando] = useState(false);
  const [porEliminar, setPorEliminar] = useState<Plantilla | null>(null);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const navegar = useNavigate();

  const refrescar = () => qc.invalidateQueries({ queryKey: ["constancias", "plantillas"] });

  async function accion(fn: () => Promise<unknown>, exito?: string) {
    setAviso(null);
    try {
      await fn();
      if (exito) setAviso({ tipo: "ok", texto: exito });
      await refrescar();
    } catch (e) {
      setAviso({ tipo: "error", texto: mensajeDeError(e) });
    }
  }

  const duplicar = async (p: Plantilla) => {
    setAviso(null);
    try {
      const copia = await duplicarPlantilla(p.id);
      await refrescar();
      navegar(`/constancias/${copia.id}`);
    } catch (e) {
      setAviso({ tipo: "error", texto: mensajeDeError(e) });
    }
  };

  return (
    <div className="cons">
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
        <button type="button" className="btn btn-primario" onClick={() => setCreando(true)}>
          {t.listado.nueva}
        </button>
      </div>
      <Pestanas />
      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}
      {plantillas.isPending && <p role="status">{t.cargando}</p>}
      {plantillas.isError && (
        <p className="alerta-error" role="alert">
          {t.errorCarga}
        </p>
      )}
      {plantillas.data && (
        <div className="tarjeta cons-tarjeta">
          {plantillas.data.length === 0 ? (
            <p className="cons-vacio">{t.listado.vacio}</p>
          ) : (
            <table className="tabla" aria-label={t.listado.tablaAria}>
              <thead>
                <tr>
                  <th scope="col">{t.listado.columnas.plantilla}</th>
                  <th scope="col">{t.listado.columnas.version}</th>
                  <th scope="col">{t.listado.columnas.actualizada}</th>
                  <th scope="col">{t.listado.columnas.emitidas}</th>
                  <th scope="col">{t.listado.columnas.estado}</th>
                  <th scope="col">{t.listado.columnas.acciones}</th>
                </tr>
              </thead>
              <tbody>
                {plantillas.data.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.nombre}</strong>
                      {p.descripcion && <div className="cons-suave">{p.descripcion}</div>}
                    </td>
                    <td>{p.version ? <span className="cons-version">{`v${p.version}`}</span> : <span className="cons-suave">{t.listado.sinVersion}</span>}</td>
                    <td className="cons-suave">{fechaMedia(p.fecha_modificacion)}</td>
                    <td>{p.emitidas}</td>
                    <td>
                      <span className={`insignia ${CLASE_ESTADO[p.estado] ?? "neutro"}`}>{t.listado.estados[p.estado] ?? p.estado}</span>
                    </td>
                    <td className="cons-acciones">
                      <Link to={`/constancias/${p.id}`} aria-label={`${t.listado.editar} ${p.nombre}`}>
                        {t.listado.editar}
                      </Link>
                      <button type="button" className="btn-enlace" aria-label={`${t.listado.duplicar} ${p.nombre}`} onClick={() => void duplicar(p)}>
                        {t.listado.duplicar}
                      </button>
                      {p.estado !== "BORRADOR" && (
                        <button
                          type="button"
                          className="btn-enlace"
                          aria-label={`${p.activa ? t.listado.desactivar : t.listado.activar} ${p.nombre}`}
                          onClick={() => void accion(() => actualizarPlantilla(p.id, { activa: !p.activa }))}
                        >
                          {p.activa ? t.listado.desactivar : t.listado.activar}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn-enlace cons-peligro"
                        aria-label={`${t.listado.eliminar} ${p.nombre}`}
                        onClick={() => setPorEliminar(p)}
                      >
                        {t.listado.eliminar}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {creando && <NuevaPlantilla alCerrar={() => setCreando(false)} />}
      {porEliminar && (
        <Dialogo
          titulo={t.listado.confirmarEliminarTitulo}
          alCerrar={() => setPorEliminar(null)}
          acciones={
            <>
              <button type="button" className="btn btn-contorno" onClick={() => setPorEliminar(null)}>
                {t.listado.cancelar}
              </button>
              <button
                type="button"
                className="btn btn-peligro"
                onClick={() => {
                  const p = porEliminar;
                  setPorEliminar(null);
                  void accion(() => eliminarPlantilla(p.id), t.listado.eliminada);
                }}
              >
                {t.listado.confirmarEliminarBoton}
              </button>
            </>
          }
        >
          <p>{t.listado.confirmarEliminar(porEliminar.nombre)}</p>
        </Dialogo>
      )}
    </div>
  );
}
