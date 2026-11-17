import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { CLAVE_ESTADO, leerEstadoMeta } from "@/features/integraciones/api";
import { aplicarErroresDeCampo } from "@/shared/errores";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { Campo } from "@/shared/ui/Campo";
import { apiPlantillasMensaje, CLAVES, type PlantillaMensaje } from "../api";
import { Dialogo, InsigniaMeta, mensajeError } from "../comun";
import { t } from "../textos";
import { ImportarDesdeMeta } from "./ImportarDesdeMeta";
import { tImportar } from "./textos";
import "../notificaciones.css";

const esquema = z.object({
  nombre: z
    .string()
    .trim()
    .min(1, t.plantillas.creacion.nombreRequerido)
    .max(512)
    .regex(/^[a-z0-9_]+$/, "Usa solo minúsculas, números y guiones bajos."),
  categoria: z.enum(["UTILITY", "MARKETING", "AUTHENTICATION"]),
  idioma: z.string().trim().min(2, "Indica el idioma.").max(10),
  texto_con_variables: z.string().trim().min(1, t.plantillas.creacion.textoRequerido).max(1024),
});
type Entrada = z.infer<typeof esquema>;

function NuevaPlantilla({ alCerrar, alCrear }: { alCerrar: () => void; alCrear: () => void }) {
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const idCategoria = useId();
  const idTexto = useId();
  const { register, handleSubmit, setError, formState } = useForm<Entrada>({
    resolver: zodResolver(esquema),
    defaultValues: { nombre: "", categoria: "UTILITY", idioma: "es_MX", texto_con_variables: "" },
  });

  const enviar = handleSubmit(async (v) => {
    setErrorGeneral(null);
    try {
      await apiPlantillasMensaje.crear({ ...v, ejemplos: [] });
      alCrear();
    } catch (e) {
      if (!aplicarErroresDeCampo(e, setError)) setErrorGeneral(mensajeError(e));
    }
  });

  return (
    <Dialogo
      titulo={t.plantillas.creacion.titulo}
      alCerrar={alCerrar}
      acciones={
        <>
          <button type="button" className="btn btn-contorno" onClick={alCerrar}>
            {t.cancelar}
          </button>
          <button type="submit" form="not-form-plantilla" className="btn btn-primario" disabled={formState.isSubmitting}>
            {t.plantillas.creacion.crear}
          </button>
        </>
      }
    >
      <form id="not-form-plantilla" onSubmit={(e) => void enviar(e)} noValidate>
        {errorGeneral && (
          <p className="alerta-error" role="alert">
            {errorGeneral}
          </p>
        )}
        <Campo etiqueta={t.plantillas.creacion.nombre} error={formState.errors.nombre?.message} {...register("nombre")} />
        <div className="campo">
          <label htmlFor={idCategoria}>{t.plantillas.creacion.categoria}</label>
          <select id={idCategoria} {...register("categoria")}>
            {Object.entries(t.plantillas.categorias).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <Campo etiqueta={t.plantillas.creacion.idioma} error={formState.errors.idioma?.message} {...register("idioma")} />
        <div className="campo">
          <label htmlFor={idTexto}>{t.plantillas.creacion.texto}</label>
          <textarea
            id={idTexto}
            rows={4}
            aria-invalid={formState.errors.texto_con_variables ? true : undefined}
            {...register("texto_con_variables")}
          />
          {formState.errors.texto_con_variables && (
            <span className="error" role="alert">
              {formState.errors.texto_con_variables.message}
            </span>
          )}
        </div>
      </form>
    </Dialogo>
  );
}

/** Catálogo de plantillas de mensaje con su estado en Meta (cv1_08, CC-REQ-117). */
export function PlantillasMensaje() {
  const qc = useQueryClient();
  const plantillas = useQuery({ queryKey: CLAVES.plantillas, queryFn: () => apiPlantillasMensaje.listar() });
  const { tiene } = useSesion();
  const puedeVerMeta = tiene("integraciones:administrar");
  // Solo quien administra la integración la consulta; si falla, simplemente no hay aviso.
  const meta = useQuery({ queryKey: CLAVE_ESTADO, queryFn: leerEstadoMeta, enabled: puedeVerMeta });
  const [creando, setCreando] = useState(false);
  const [importando, setImportando] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);

  async function accion(fn: () => Promise<unknown>, exito: string) {
    setAviso(null);
    try {
      await fn();
      setAviso({ tipo: "ok", texto: exito });
      await qc.invalidateQueries({ queryKey: CLAVES.plantillas });
    } catch (e) {
      setAviso({ tipo: "error", texto: mensajeError(e) });
    }
  }

  const puedeRevisar = (p: PlantillaMensaje) => p.estado_meta === "BORRADOR" || p.estado_meta === "RECHAZADA";

  return (
    <div className="not">
      <div className="encabezado">
        <div>
          <h1>{t.plantillas.titulo}</h1>
          <p>{t.plantillas.subtitulo}</p>
          <nav aria-label="Ruta de navegación" className="not-migas">
            <Link to="/notificaciones">{t.migas.notificaciones}</Link> / {t.migas.plantillas}
          </nav>
        </div>
        <div className="not-acciones">
          {puedeVerMeta && (
            <Link className="btn btn-contorno" to="/integraciones/meta">
              {t.plantillas.conexionMeta}
            </Link>
          )}
          <button type="button" className="btn btn-contorno" onClick={() => setImportando(true)}>
            {tImportar.boton}
          </button>
          <button type="button" className="btn btn-primario" onClick={() => setCreando(true)}>
            {t.plantillas.nueva}
          </button>
        </div>
      </div>

      {puedeVerMeta && meta.data && !meta.data.configurada && (
        <p className="alerta-info" role="note">
          {t.plantillas.metaSinConfigurar}{" "}
          <Link to="/integraciones/meta">{t.plantillas.conexionMeta}</Link>
        </p>
      )}

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
        <div className="tarjeta not-tarjeta">
          {plantillas.data.items.length === 0 ? (
            <p className="not-vacio">{t.plantillas.vacio}</p>
          ) : (
            <table className="tabla" aria-label={t.plantillas.tablaAria}>
              <thead>
                <tr>
                  <th scope="col">{t.plantillas.columnas.nombre}</th>
                  <th scope="col">{t.plantillas.columnas.categoria}</th>
                  <th scope="col">{t.plantillas.columnas.variables}</th>
                  <th scope="col">{t.plantillas.columnas.estado}</th>
                  <th scope="col">{t.plantillas.columnas.acciones}</th>
                </tr>
              </thead>
              <tbody>
                {plantillas.data.items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong className="not-plantilla">{p.nombre}</strong>
                      <div className="not-suave not-texto-plantilla">{p.texto_con_variables}</div>
                    </td>
                    <td>{t.plantillas.categorias[p.categoria] ?? p.categoria}</td>
                    <td className="not-variables-nombres">
                      {t.plantillas.variables(p.cantidad_variables)}
                      {p.formato_variables === "NOMBRADO" && (
                        <>
                          <br />
                          <span className="insignia not-info">{t.plantillas.variablesConNombre}</span>
                          <br />
                          {p.variables.map((v, i) => (
                            <span key={v}>
                              {i > 0 && ", "}
                              <code>{v}</code>
                            </span>
                          ))}
                        </>
                      )}
                    </td>
                    <td>
                      <InsigniaMeta estado={p.estado_meta} />
                      {p.estado_meta === "RECHAZADA" && p.motivo_rechazo && (
                        <p className="not-rechazo">
                          <strong>{t.plantillas.motivoRechazo}:</strong> {p.motivo_rechazo}
                        </p>
                      )}
                    </td>
                    <td className="not-acciones">
                      <button
                        type="button"
                        className="btn-enlace"
                        aria-label={`${t.plantillas.duplicar} ${p.nombre}`}
                        onClick={() => void accion(() => apiPlantillasMensaje.duplicar(p.id), t.plantillas.duplicada)}
                      >
                        {t.plantillas.duplicar}
                      </button>
                      {puedeRevisar(p) && (
                        <button
                          type="button"
                          className="btn-enlace"
                          aria-label={`${t.plantillas.enviarRevision} ${p.nombre}`}
                          onClick={() => void accion(() => apiPlantillasMensaje.enviarARevision(p.id), t.plantillas.enviada)}
                        >
                          {t.plantillas.enviarRevision}
                        </button>
                      )}
                      {p.estado_meta === "EN_REVISION" && (
                        <button
                          type="button"
                          className="btn-enlace"
                          aria-label={`${t.plantillas.sincronizar} ${p.nombre}`}
                          onClick={() => void accion(() => apiPlantillasMensaje.sincronizar(p.id), t.plantillas.sincronizada)}
                        >
                          {t.plantillas.sincronizar}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {importando && (
        <ImportarDesdeMeta
          alCerrar={() => setImportando(false)}
          alImportar={(n) => {
            setAviso({ tipo: "ok", texto: tImportar.resumen.importadas(n) });
            void qc.invalidateQueries({ queryKey: CLAVES.plantillas });
          }}
        />
      )}
      {creando && (
        <NuevaPlantilla
          alCerrar={() => setCreando(false)}
          alCrear={() => {
            setCreando(false);
            setAviso({ tipo: "ok", texto: t.plantillas.creada });
            void qc.invalidateQueries({ queryKey: CLAVES.plantillas });
          }}
        />
      )}
    </div>
  );
}
