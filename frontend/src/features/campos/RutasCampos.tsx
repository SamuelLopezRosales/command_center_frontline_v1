import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { CLAVE_CAMPOS, apiCampos, type CampoDto } from "./api";
import "./campos.css";
import { PanelCampo } from "./PanelCampo";
import { TIPOS, textos as t } from "./textos";

type Pestana = "todos" | "sugeridos" | "personalizados";

function ConfiguracionCampos() {
  const [pestana, setPestana] = useState<Pestana>("todos");
  const [seleccion, setSeleccion] = useState<number | "nuevo" | null>(null);
  const consulta = useQuery({ queryKey: [...CLAVE_CAMPOS, "listado"], queryFn: () => apiCampos.listar("todos") });

  const fijos = consulta.data?.fijos ?? [];
  const dinamicos = consulta.data?.dinamicos ?? [];
  const sugeridos = dinamicos.filter((c) => c.es_sugerido);
  const personalizados = dinamicos.filter((c) => !c.es_sugerido);
  const visibles: CampoDto[] = pestana === "todos" ? dinamicos : pestana === "sugeridos" ? sugeridos : personalizados;
  const campoSeleccionado = typeof seleccion === "number" ? (dinamicos.find((c) => c.id === seleccion) ?? null) : null;

  const pestanas: { id: Pestana; texto: string; total: number }[] = [
    { id: "todos", texto: t.pestanas.todos, total: fijos.length + dinamicos.length },
    { id: "sugeridos", texto: t.pestanas.sugeridos, total: sugeridos.length },
    { id: "personalizados", texto: t.pestanas.personalizados, total: personalizados.length },
  ];

  return (
    <>
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          <Link className="btn btn-contorno" to="/colaboradores">
            {t.volver}
          </Link>
          <button className="btn btn-primario" onClick={() => setSeleccion("nuevo")}>
            {t.nuevo}
          </button>
        </div>
      </div>

      <div className="cam-pestanas" role="tablist" aria-label="Tipo de campo">
        {pestanas.map((p) => (
          <button key={p.id} role="tab" className="cam-pestana" aria-selected={pestana === p.id} onClick={() => setPestana(p.id)}>
            {p.texto} ({p.total})
          </button>
        ))}
      </div>

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
        <div className="cam-cuerpo">
          <section className="tarjeta cam-tabla" aria-label="Campos">
            <table className="tabla">
              <thead>
                <tr>
                  <th>{t.columnas.campo}</th>
                  <th>{t.columnas.clave}</th>
                  <th>{t.columnas.tipo}</th>
                  <th>{t.columnas.obligatorio}</th>
                  <th>{t.columnas.sensible}</th>
                  <th>{t.columnas.estado}</th>
                  <th>
                    <span className="sr-solo">{t.columnas.accion}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {pestana === "todos" && (
                  <>
                    <tr className="cam-grupo">
                      <td colSpan={7}>{t.fijos(fijos.length)}</td>
                    </tr>
                    {fijos.map((f) => (
                      <tr key={f.clave} className="cam-fijo" data-fijo={f.clave}>
                        <td>{f.nombre}</td>
                        <td className="cam-clave">{`{{${f.clave}}}`}</td>
                        <td>{TIPOS[f.tipo_dato]}</td>
                        <td>
                          <input type="checkbox" checked={f.obligatorio} disabled readOnly aria-label={`${t.columnas.obligatorio} ${f.nombre}`} />
                        </td>
                        <td>—</td>
                        <td>
                          <span className="insignia ok">{t.activo}</span>
                        </td>
                        <td />
                      </tr>
                    ))}
                  </>
                )}
                {visibles.map((c) => (
                  <tr key={c.id} data-campo={c.codigo_interno}>
                    <td style={{ fontWeight: c.es_sugerido ? undefined : 700 }}>{c.nombre_campo}</td>
                    <td className="cam-clave">{`{{${c.clave}}}`}</td>
                    <td>{TIPOS[c.tipo_dato]}</td>
                    <td>
                      <input type="checkbox" checked={c.obligatorio} disabled readOnly aria-label={`${t.columnas.obligatorio} ${c.nombre_campo}`} />
                    </td>
                    <td>{c.es_sensible ? <span className="insignia error">{t.sensible}</span> : "—"}</td>
                    <td>
                      <span className={`insignia ${c.activo ? "ok" : "neutro"}`}>{c.activo ? t.activo : t.inactivo}</span>
                    </td>
                    <td>
                      <button className="btn-enlace" aria-label={`${t.editar} ${c.nombre_campo}`} onClick={() => setSeleccion(c.id)}>
                        {t.editar}
                      </button>
                    </td>
                  </tr>
                ))}
                {visibles.length === 0 && pestana !== "todos" && (
                  <tr>
                    <td colSpan={7}>{t.vacio}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>

          {seleccion === "nuevo" && (
            <PanelCampo key="nuevo" campo={null} onCerrar={() => setSeleccion(null)} onGuardado={(c) => setSeleccion(c.id)} />
          )}
          {campoSeleccionado && (
            <PanelCampo key={campoSeleccionado.id} campo={campoSeleccionado} onCerrar={() => setSeleccion(null)} onGuardado={() => undefined} />
          )}
        </div>
      )}
    </>
  );
}

export function RutasCampos() {
  return (
    <Routes>
      <Route index element={<ConfiguracionCampos />} />
      <Route path="*" element={<Navigate to="/campos" replace />} />
    </Routes>
  );
}
