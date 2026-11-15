import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ErrorApi, aplicarErroresDeCampo, mensajeDeError } from "@/shared/errores";
import { Campo } from "@/shared/ui/Campo";
import { CLAVE_CAMPOS, apiCampos, type CampoActualizar, type CampoDto, type OpcionDto, type TipoDato } from "./api";
import { TIPOS, textos as t } from "./textos";

const CLAVE = /^[a-z][a-z0-9_]{1,40}$/;
const VALOR_OPCION = /^[A-Z0-9_]{1,40}$/;

const esquema = z.object({
  nombre_campo: z.string().trim().min(1, t.panel.requerido),
  clave: z.string().regex(CLAVE, t.panel.claveInvalida),
  tipo_dato: z.enum(["TEXTO", "NUMERO", "FECHA", "LISTA", "SI_NO"]),
  formato_validacion: z.string().max(200),
  obligatorio: z.boolean(),
  es_sensible: z.boolean(),
  activo: z.boolean(),
});
type Valores = z.infer<typeof esquema>;

interface PlantillaAfectada {
  id: number;
  nombre: string;
}

function plantillasDe(error: ErrorApi): PlantillaAfectada[] {
  const p = error.detalle["plantillas"];
  return Array.isArray(p) ? (p as PlantillaAfectada[]) : [];
}

interface Props {
  campo: CampoDto | null;
  onCerrar(): void;
  onGuardado(campo: CampoDto): void;
}

export function PanelCampo({ campo, onCerrar, onGuardado }: Props) {
  const cliente = useQueryClient();
  const idTipo = useId();
  const edicion = campo !== null;
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [uso, setUso] = useState<{ plantillas: PlantillaAfectada[]; cambios: CampoActualizar } | null>(null);
  const [eliminando, setEliminando] = useState(false);

  const { register, handleSubmit, setError: setErrorCampo, watch, formState } = useForm<Valores>({
    resolver: zodResolver(esquema),
    defaultValues: {
      nombre_campo: campo?.nombre_campo ?? "",
      clave: campo?.clave ?? "",
      tipo_dato: campo?.tipo_dato ?? "TEXTO",
      formato_validacion: campo?.formato_validacion ?? "",
      obligatorio: campo?.obligatorio ?? false,
      es_sensible: campo?.es_sensible ?? false,
      activo: campo?.activo ?? true,
    },
  });
  const { errors, isSubmitting } = formState;
  const tipo = watch("tipo_dato") as TipoDato;

  const refrescar = () => cliente.invalidateQueries({ queryKey: CLAVE_CAMPOS });

  async function enviarCambios(cambios: CampoActualizar) {
    if (!campo) return;
    try {
      const guardado = await apiCampos.actualizar(campo.id, cambios);
      setUso(null);
      setError(null);
      setAviso(t.panel.guardado);
      await refrescar();
      onGuardado(guardado);
    } catch (e) {
      if (e instanceof ErrorApi && e.codigo === "CLAVE_EN_USO_REQUIERE_CONFIRMACION") {
        setUso({ plantillas: plantillasDe(e), cambios });
        return;
      }
      if (!aplicarErroresDeCampo(e, setErrorCampo)) setError(mensajeDeError(e));
    }
  }

  async function alEnviar(v: Valores) {
    setError(null);
    setAviso(null);
    const formato = v.formato_validacion.trim();
    if (!campo) {
      try {
        const creado = await apiCampos.crear({
          nombre_campo: v.nombre_campo.trim(),
          clave: v.clave,
          tipo_dato: v.tipo_dato,
          formato_validacion: formato || null,
          obligatorio: v.obligatorio,
          es_sensible: v.es_sensible,
        });
        setAviso(t.panel.guardado);
        await refrescar();
        onGuardado(creado);
      } catch (e) {
        if (!aplicarErroresDeCampo(e, setErrorCampo)) setError(mensajeDeError(e));
      }
      return;
    }
    const cambios: CampoActualizar = {};
    if (v.nombre_campo.trim() !== campo.nombre_campo) cambios.nombre_campo = v.nombre_campo.trim();
    if (v.clave !== campo.clave) cambios.clave = v.clave;
    if (v.tipo_dato !== campo.tipo_dato) cambios.tipo_dato = v.tipo_dato;
    if (formato !== (campo.formato_validacion ?? "")) cambios.formato_validacion = formato || null;
    if (v.obligatorio !== campo.obligatorio) cambios.obligatorio = v.obligatorio;
    if (v.es_sensible !== campo.es_sensible) cambios.es_sensible = v.es_sensible;
    if (v.activo !== campo.activo) cambios.activo = v.activo;
    if (Object.keys(cambios).length === 0) {
      setAviso(t.panel.sinCambios);
      return;
    }
    await enviarCambios(cambios);
  }

  async function alternarActivo() {
    if (!campo) return;
    setError(null);
    await enviarCambios({ activo: !campo.activo });
  }

  async function eliminar() {
    if (!campo) return;
    try {
      await apiCampos.eliminar(campo.id);
      await refrescar();
      onCerrar();
    } catch (e) {
      setEliminando(false);
      setError(mensajeDeError(e));
    }
  }

  return (
    <aside className="tarjeta cam-panel" aria-label={edicion ? t.panel.editar : t.panel.nuevo}>
      <h2>{edicion ? t.panel.editar : t.panel.nuevo}</h2>
      {campo && (
        <span className="cam-etiqueta">
          {campo.es_sugerido ? t.panel.sugerido : t.panel.personalizado} · {TIPOS[campo.tipo_dato]}
        </span>
      )}
      {error && (
        <div className="alerta-error" role="alert">
          {error}
        </div>
      )}
      {aviso && (
        <div className="alerta-info" role="status">
          {aviso}
        </div>
      )}

      <form onSubmit={handleSubmit(alEnviar)} noValidate>
        <Campo etiqueta={t.panel.nombre} error={errors.nombre_campo?.message} {...register("nombre_campo")} />
        <Campo
          etiqueta={t.panel.clave}
          error={errors.clave?.message}
          ayuda={edicion ? undefined : t.panel.claveAyuda}
          disabled={campo?.es_sugerido}
          {...register("clave")}
        />
        {campo && (
          <>
            {campo.usada_en_plantillas ? <p className="cam-nota">{t.panel.usadaEn(campo.usada_en_plantillas)}</p> : null}
            <p className="cam-nota">{t.panel.codigoInterno(campo.codigo_interno)}</p>
          </>
        )}

        <div className="campo">
          <label htmlFor={idTipo}>{t.panel.tipo}</label>
          <select id={idTipo} disabled={campo?.es_sugerido} {...register("tipo_dato")}>
            {(Object.keys(TIPOS) as TipoDato[]).map((k) => (
              <option key={k} value={k}>
                {TIPOS[k]}
              </option>
            ))}
          </select>
          {campo?.es_sugerido && <span className="ayuda">{t.panel.tipoBloqueado}</span>}
        </div>

        <Campo etiqueta={t.panel.formato} error={errors.formato_validacion?.message} maxLength={200} {...register("formato_validacion")} />

        <div className="cam-casillas">
          <label>
            <input type="checkbox" {...register("obligatorio")} /> {t.panel.obligatorio}
          </label>
          <label>
            <input type="checkbox" {...register("es_sensible")} /> {t.panel.sensibleCifra}
          </label>
          {edicion && (
            <label>
              <input type="checkbox" {...register("activo")} /> {t.panel.activo}
            </label>
          )}
        </div>

        {uso && (
          <div className="cam-aviso" role="alertdialog" aria-label={t.uso.titulo}>
            <strong>{t.uso.titulo}</strong>
            <p>{t.uso.texto}</p>
            <ul>
              {uso.plantillas.map((p) => (
                <li key={p.id}>{p.nombre}</li>
              ))}
            </ul>
            <button type="button" className="btn btn-primario" onClick={() => void enviarCambios({ ...uso.cambios, confirmar: true })}>
              {t.uso.confirmar}
            </button>{" "}
            <button type="button" className="btn" onClick={() => setUso(null)}>
              {t.uso.cancelar}
            </button>
          </div>
        )}

        <div className="cam-acciones">
          {campo && (
            <button type="button" className="btn btn-peligro" onClick={() => void alternarActivo()}>
              {campo.activo ? t.panel.desactivar : t.panel.activar}
            </button>
          )}
          <button type="submit" className="btn btn-primario" disabled={isSubmitting}>
            {t.panel.guardar}
          </button>
        </div>
        <div className="cam-acciones">
          <button type="button" className="btn" onClick={onCerrar}>
            {t.panel.cerrar}
          </button>
          {campo && !campo.es_sugerido &&
            (eliminando ? (
              <button type="button" className="btn btn-peligro" onClick={() => void eliminar()}>
                {t.panel.confirmarEliminar}
              </button>
            ) : (
              <button type="button" className="btn btn-peligro" onClick={() => setEliminando(true)}>
                {t.panel.eliminar}
              </button>
            ))}
        </div>
      </form>

      {campo && tipo === "LISTA" && campo.tipo_dato === "LISTA" && <Opciones campo={campo} alCambiar={refrescar} />}
    </aside>
  );
}

function Opciones({ campo, alCambiar }: { campo: CampoDto; alCambiar(): Promise<unknown> }) {
  const [abierta, setAbierta] = useState(false);
  const [etiqueta, setEtiqueta] = useState("");
  const [valor, setValor] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const opciones: OpcionDto[] = [...(campo.opciones ?? [])].sort((a, b) => a.orden - b.orden);

  async function agregar() {
    setError(null);
    const v = valor.trim() || etiqueta.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_");
    if (!etiqueta.trim()) return setError(t.panel.requerido);
    if (!VALOR_OPCION.test(v)) return setError(t.panel.valorInvalido);
    try {
      await apiCampos.crearOpcion(campo.id, { etiqueta: etiqueta.trim(), valor: v, descripcion: descripcion.trim() || null });
      setEtiqueta("");
      setValor("");
      setDescripcion("");
      setAbierta(false);
      await alCambiar();
    } catch (e) {
      setError(mensajeDeError(e));
    }
  }

  async function alternar(o: OpcionDto) {
    try {
      await apiCampos.actualizarOpcion(campo.id, o.id, { activo: !o.activo });
      await alCambiar();
    } catch (e) {
      setError(mensajeDeError(e));
    }
  }

  return (
    <section aria-label={t.panel.opciones}>
      <h3 className="cam-sub">{t.panel.opciones}</h3>
      {opciones.length === 0 && <p className="cam-nota">{t.panel.sinOpciones}</p>}
      <ul className="cam-opciones">
        {opciones.map((o) => (
          <li key={o.id} className={`cam-opcion${o.activo ? "" : " inactiva"}`}>
            <span>
              <strong>{o.etiqueta}</strong> {o.descripcion && <small>{o.descripcion}</small>}
            </span>
            <button
              type="button"
              className="btn-enlace"
              aria-label={`${o.activo ? t.panel.desactivarOpcion : t.panel.activarOpcion}: ${o.etiqueta}`}
              onClick={() => void alternar(o)}
            >
              {o.activo ? t.panel.activo : t.inactivo}
            </button>
          </li>
        ))}
      </ul>
      {error && (
        <div className="alerta-error" role="alert">
          {error}
        </div>
      )}
      {abierta ? (
        <div>
          <Campo etiqueta={t.panel.opcionEtiqueta} value={etiqueta} onChange={(e) => setEtiqueta(e.target.value)} />
          <Campo etiqueta={t.panel.opcionValor} value={valor} onChange={(e) => setValor(e.target.value.toUpperCase())} />
          <Campo etiqueta={t.panel.opcionDescripcion} value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
          <button type="button" className="btn btn-primario" onClick={() => void agregar()}>
            {t.panel.guardarOpcion}
          </button>
        </div>
      ) : (
        <button type="button" className="btn-enlace" onClick={() => setAbierta(true)}>
          {t.panel.agregarOpcion}
        </button>
      )}
    </section>
  );
}
