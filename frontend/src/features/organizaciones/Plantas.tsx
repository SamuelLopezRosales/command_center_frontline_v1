import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { aplicarErroresDeCampo, mensajeDeError } from "@/shared/errores";
import { Campo } from "@/shared/ui/Campo";
import { CLAVE_PLANTAS, apiPlantas, type Planta } from "./api";
import { textos as t } from "./textos";

const T = t.planta;

export function Plantas() {
  const cliente = useQueryClient();
  const consulta = useQuery({ queryKey: [...CLAVE_PLANTAS], queryFn: () => apiPlantas.listar(false) });
  const [nombre, setNombre] = useState("");
  const [errorNombre, setErrorNombre] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [editando, setEditando] = useState<{ id: number; nombre: string } | null>(null);
  const refrescar = () => cliente.invalidateQueries({ queryKey: CLAVE_PLANTAS });

  async function ejecutar(accion: () => Promise<unknown>, campo?: (m: string) => void) {
    setError(null);
    try {
      await accion();
      await refrescar();
      return true;
    } catch (e) {
      const mensajes: string[] = [];
      if (!aplicarErroresDeCampo(e, (_c, err) => mensajes.push(err.message))) setError(mensajeDeError(e));
      else if (campo) campo(mensajes[0] ?? "");
      return false;
    }
  }

  async function agregar(ev: FormEvent) {
    ev.preventDefault();
    setErrorNombre(undefined);
    if (!nombre.trim()) return setErrorNombre(t.requerido);
    const ok = await ejecutar(() => apiPlantas.crear(nombre.trim()), setErrorNombre);
    if (ok) setNombre("");
  }

  async function renombrar(p: Planta) {
    if (!editando || !editando.nombre.trim()) return;
    const ok = await ejecutar(() => apiPlantas.actualizar(p.id, { nombre: editando.nombre.trim() }));
    if (ok) setEditando(null);
  }

  const plantas = consulta.data ?? [];
  return (
    <>
      <form className="tarjeta org-nuevaplanta" onSubmit={(e) => void agregar(e)} noValidate aria-label={T.nueva}>
        <Campo etiqueta={T.nombre} value={nombre} error={errorNombre} onChange={(e) => setNombre(e.target.value)} />
        <button type="submit" className="btn btn-primario">
          {T.agregar}
        </button>
      </form>
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
      {consulta.data && (
        <section className="tarjeta org-tabla" aria-label={t.pestanas.plantas}>
          <table className="tabla">
            <thead>
              <tr>
                <th>{T.columnas.nombre}</th>
                <th>{T.columnas.estado}</th>
                <th>{T.columnas.accion}</th>
              </tr>
            </thead>
            <tbody>
              {plantas.map((p) => (
                <tr key={p.id}>
                  <td>
                    {editando?.id === p.id ? (
                      <span className="org-renombrar">
                        <input
                          aria-label={`${T.nombre} ${p.nombre}`}
                          value={editando.nombre}
                          onChange={(e) => setEditando({ id: p.id, nombre: e.target.value })}
                        />
                        <button className="btn btn-primario" onClick={() => void renombrar(p)}>
                          {T.guardar}
                        </button>
                        <button className="btn" onClick={() => setEditando(null)}>
                          {T.cancelar}
                        </button>
                      </span>
                    ) : (
                      p.nombre
                    )}
                  </td>
                  <td>
                    <span className={`insignia ${p.activa ? "ok" : "neutro"}`}>{p.activa ? t.activa : t.inactiva}</span>
                  </td>
                  <td>
                    <button className="btn-enlace" aria-label={`${T.renombrar} ${p.nombre}`} onClick={() => setEditando({ id: p.id, nombre: p.nombre })}>
                      {T.renombrar}
                    </button>{" "}
                    <button
                      className="btn-enlace"
                      aria-label={`${p.activa ? T.desactivar : T.activar} ${p.nombre}`}
                      onClick={() => void ejecutar(() => apiPlantas.actualizar(p.id, { activa: !p.activa }))}
                    >
                      {p.activa ? T.desactivar : T.activar}
                    </button>
                  </td>
                </tr>
              ))}
              {plantas.length === 0 && (
                <tr>
                  <td colSpan={3}>{T.vacio}</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
