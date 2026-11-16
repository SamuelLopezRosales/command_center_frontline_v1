import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi } from "@/shared/errores";
import { fechaHora } from "@/shared/fechas";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { desactivarUsuario, listarUsuarios, type UsuarioItem } from "./api";
import { Dialogo } from "./Dialogo";
import { DialogoInvitacion } from "./DialogoInvitacion";
import { t } from "./textos";
import "./usuarios.css";

function mensajeDesactivar(e: unknown): string {
  if (e instanceof ErrorApi) return t.desactivar.errores[e.codigo] ?? t.desactivar.errorGeneral;
  return t.desactivar.errorGeneral;
}

/** Administración de usuarios (DSH-08 a DSH-10). */
export function ListadoUsuarios() {
  const { estado, tiene, usuario } = useSesion();
  const cliente = useQueryClient();
  const puede = tiene("usuarios:administrar");
  const usuarios = useQuery({ queryKey: ["usuarios", "lista"], queryFn: listarUsuarios, enabled: puede });
  const [aDesactivar, setADesactivar] = useState<UsuarioItem | null>(null);
  const [invitando, setInvitando] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [errorDialogo, setErrorDialogo] = useState<string | null>(null);

  const desactivar = useMutation({
    mutationFn: (u: UsuarioItem) => desactivarUsuario(u.id),
    onSuccess: (_r, u) => {
      setADesactivar(null);
      setAviso({ tipo: "ok", texto: t.listado.desactivado(u.nombre) });
      void cliente.invalidateQueries({ queryKey: ["usuarios", "lista"] });
    },
    onError: (e) => {
      setErrorDialogo(mensajeDesactivar(e));
      // Si el estado cambió en el servidor (ya no existe, etc.), la lista se vuelve a leer.
      void cliente.invalidateQueries({ queryKey: ["usuarios", "lista"] });
    },
  });

  if (estado === "cargando") return <p role="status">{t.cargando}</p>;
  if (!puede)
    return (
      <div className="usr">
        <h1>{t.titulo}</h1>
        <p className="alerta-error" role="alert">
          {t.sinPermiso}
        </p>
      </div>
    );

  return (
    <div className="usr">
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
        <div className="usr-acciones">
          {tiene("bitacora:ver") && (
            <Link className="btn btn-contorno usr-enlace-boton" to="/usuarios/bitacora">
              {t.bitacora}
            </Link>
          )}
          <button type="button" className="btn btn-primario" onClick={() => setInvitando(true)}>
            {t.listado.invitar}
          </button>
        </div>
      </div>

      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}
      {usuarios.isPending && <p role="status">{t.cargando}</p>}
      {usuarios.isError && (
        <p className="alerta-error" role="alert">
          {t.errorCarga}{" "}
          <button type="button" className="btn-enlace" onClick={() => void usuarios.refetch()}>
            {t.reintentar}
          </button>
        </p>
      )}
      {usuarios.data && (
        <div className="tarjeta usr-tarjeta">
          {usuarios.data.length === 0 ? (
            <p className="usr-vacio">{t.listado.vacio}</p>
          ) : (
            <table className="tabla" aria-label={t.listado.tablaAria}>
              <thead>
                <tr>
                  <th scope="col">{t.listado.columnas.nombre}</th>
                  <th scope="col">{t.listado.columnas.correo}</th>
                  <th scope="col">{t.listado.columnas.rol}</th>
                  <th scope="col">{t.listado.columnas.estado}</th>
                  <th scope="col">{t.listado.columnas.actividad}</th>
                  <th scope="col">{t.listado.columnas.acciones}</th>
                </tr>
              </thead>
              <tbody>
                {usuarios.data.map((u) => {
                  const yo = u.id === usuario?.id;
                  return (
                    <tr key={u.id}>
                      <td>
                        {u.nombre} {yo && <span className="usr-suave">{t.listado.tu}</span>}
                      </td>
                      <td className="usr-suave">{u.correo}</td>
                      <td>{u.rol}</td>
                      <td>
                        <span className={`insignia ${u.activo ? "ok" : "neutro"}`}>{u.activo ? t.listado.activo : t.listado.inactivo}</span>
                      </td>
                      <td className="usr-suave">{u.ultima_actividad ? fechaHora(u.ultima_actividad) : t.listado.nuncaActivo}</td>
                      <td>
                        {u.activo && !yo && (
                          <button
                            type="button"
                            className="btn-enlace usr-peligro"
                            aria-label={`${t.listado.desactivar} ${u.nombre}`}
                            onClick={() => {
                              setErrorDialogo(null);
                              setAviso(null);
                              setADesactivar(u);
                            }}
                          >
                            {t.listado.desactivar}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {aDesactivar && (
        <Dialogo
          titulo={t.desactivar.titulo}
          alCerrar={() => setADesactivar(null)}
          acciones={
            <>
              <button type="button" className="btn btn-contorno" onClick={() => setADesactivar(null)}>
                {t.desactivar.cancelar}
              </button>
              <button type="button" className="btn btn-peligro" disabled={desactivar.isPending} onClick={() => desactivar.mutate(aDesactivar)}>
                {t.desactivar.confirmar}
              </button>
            </>
          }
        >
          <p>{t.desactivar.pregunta(aDesactivar.nombre)}</p>
          {errorDialogo && (
            <p className="alerta-error" role="alert">
              {errorDialogo}
            </p>
          )}
        </Dialogo>
      )}

      {invitando && <DialogoInvitacion alCerrar={() => setInvitando(false)} />}
    </div>
  );
}
