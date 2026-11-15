import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type ReactNode } from "react";
import { useForm, type Resolver } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";
import { CLAVE_CAMPOS, apiCampos, type CampoDto, type CampoFijoDto } from "@/features/campos/api";
import {
  CLAVE_ORGANIZACIONES,
  CLAVE_PLANTAS,
  apiOrganizaciones,
  apiPlantas,
  type Organizacion,
  type Planta,
} from "@/features/organizaciones/api";
import { ErrorApi, mensajeDeError } from "@/shared/errores";
import { fechaCivil } from "@/shared/fechas";
import {
  CLAVE_COLABORADORES,
  apiColaboradores,
  type ColaboradorActualizar,
  type ColaboradorCrear,
  type ColaboradorDetalle,
} from "./api";
import "./colaboradores.css";
import { textos as tl, textosForm as T } from "./textos";

// ---------------------------------------------------------------- tipos y utilidades

interface Valores {
  numero_empleado: string;
  nombres: string;
  apellido_paterno: string;
  apellido_materno: string;
  celular: string;
  organizacion: string;
  planta: string;
  fecha_ingreso: string;
  puesto: string;
  tipo_empleado: string;
  campos: Record<string, string>;
  consentimiento: boolean;
}

const FIJOS_TEXTO = ["numero_empleado", "nombres", "apellido_paterno", "apellido_materno", "puesto"] as const;
const soloDigitos = (v: string) => v.replace(/\D/g, "");

/** Texto editable de un valor dinámico; un sensible guardado llega enmascarado y se deja vacío. */
function aTexto(valor: unknown): string {
  if (typeof valor === "string") return valor;
  if (typeof valor === "number" || typeof valor === "boolean") return String(valor);
  return "";
}

const estaOculto = (valor: unknown): boolean => typeof valor === "object" && valor !== null && "presente" in valor;

function convertir(c: CampoDto, v: string): unknown {
  if (c.tipo_dato === "NUMERO") return Number(v);
  if (c.tipo_dato === "SI_NO") return v === "true";
  return v;
}

function construirEsquema(dinamicos: CampoDto[], edicion: boolean, ocultos: Set<string>) {
  const requerido = z.string().trim().min(1, T.requerido);
  const campos = Object.fromEntries(
    dinamicos.map((c) => [
      c.codigo_interno,
      z.string().superRefine((v, ctx) => {
        const obligatorio = c.obligatorio && !(edicion && ocultos.has(c.codigo_interno));
        if (obligatorio && v.trim() === "") ctx.addIssue({ code: "custom", message: T.requerido });
        if (c.tipo_dato === "NUMERO" && v.trim() !== "" && !Number.isFinite(Number(v))) ctx.addIssue({ code: "custom", message: T.numeroInvalido });
      }),
    ]),
  );
  return z.object({
    numero_empleado: requerido,
    nombres: requerido,
    apellido_paterno: requerido,
    apellido_materno: requerido,
    celular: z.string().superRefine((v, ctx) => {
      const vacio = v.trim() === "";
      if (vacio && !edicion) ctx.addIssue({ code: "custom", message: T.requerido });
      else if (!vacio && soloDigitos(v).length !== 10) ctx.addIssue({ code: "custom", message: T.celularInvalido });
    }),
    organizacion: requerido,
    planta: requerido,
    fecha_ingreso: requerido,
    puesto: requerido,
    tipo_empleado: requerido,
    campos: z.object(campos),
    consentimiento: z.boolean(),
  });
}

interface PropsControl {
  etiqueta: string;
  requerido?: boolean;
  sensible?: boolean;
  error?: string;
  ayuda?: string;
  hijo(p: { id: string; "aria-invalid"?: boolean; "aria-describedby"?: string; "aria-required"?: boolean }): ReactNode;
}

function Control({ etiqueta, requerido, sensible, error, ayuda, hijo }: PropsControl) {
  const id = useId();
  const idMsg = `${id}-msg`;
  return (
    <div className="col-control">
      <div className="col-etiqueta">
        <label htmlFor={id} className={requerido ? "col-req" : undefined}>
          {etiqueta}
        </label>
        {sensible && <span className="col-sensible">{T.sensible}</span>}
      </div>
      {hijo({ id, "aria-invalid": error ? true : undefined, "aria-describedby": error || ayuda ? idMsg : undefined, "aria-required": requerido || undefined })}
      {error ? (
        <span id={idMsg} className="error" role="alert">
          {error}
        </span>
      ) : ayuda ? (
        <span id={idMsg} className="ayuda">
          {ayuda}
        </span>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- carga de datos

export function FormularioColaborador() {
  const { id } = useParams();
  const idNum = id && id !== "nuevo" ? Number(id) : null;
  const campos = useQuery({ queryKey: [...CLAVE_CAMPOS, "activos"], queryFn: () => apiCampos.listar("activos") });
  const orgs = useQuery({ queryKey: [...CLAVE_ORGANIZACIONES], queryFn: () => apiOrganizaciones.listar(false) });
  const plantas = useQuery({ queryKey: [...CLAVE_PLANTAS], queryFn: () => apiPlantas.listar(false) });
  const detalle = useQuery({
    queryKey: [...CLAVE_COLABORADORES, "detalle", idNum],
    queryFn: () => apiColaboradores.detalle(idNum as number),
    enabled: idNum !== null,
  });

  const error = campos.error ?? orgs.error ?? plantas.error ?? detalle.error;
  const listo = campos.data && orgs.data && plantas.data && (idNum === null || detalle.data);

  return (
    <>
      <div className="encabezado">
        <div>
          <h1>{idNum === null ? T.nuevoTitulo : T.editarTitulo}</h1>
          <p className="col-migas">
            <Link to="/colaboradores">{T.migas.colaboradores}</Link> / {idNum === null ? T.migas.nuevo : T.migas.editar}
          </p>
        </div>
      </div>
      {error && (
        <div className="alerta-error" role="alert">
          {T.errorCarga}
        </div>
      )}
      {!listo && !error && <p role="status">{T.cargando}</p>}
      {listo && (
        <Formulario
          key={detalle.data?.datos.id ?? "nuevo"}
          fijos={campos.data.fijos}
          dinamicos={campos.data.dinamicos.filter((c) => c.activo).sort((a, b) => a.orden - b.orden)}
          orgs={orgs.data}
          plantas={plantas.data}
          detalle={detalle.data?.datos ?? null}
          etag={detalle.data?.etag ?? null}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------- formulario

interface PropsFormulario {
  fijos: CampoFijoDto[];
  dinamicos: CampoDto[];
  orgs: Organizacion[];
  plantas: Planta[];
  detalle: ColaboradorDetalle | null;
  etag: string | null;
}

function Formulario({ fijos, dinamicos, orgs, plantas, detalle, etag }: PropsFormulario) {
  const edicion = detalle !== null;
  const navegar = useNavigate();
  const cliente = useQueryClient();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  const ocultos = new Set(dinamicos.filter((c) => estaOculto(detalle?.campos[c.codigo_interno])).map((c) => c.codigo_interno));
  const inicial: Valores = {
    numero_empleado: detalle?.numero_empleado ?? "",
    nombres: detalle?.nombres ?? "",
    apellido_paterno: detalle?.apellido_paterno ?? "",
    apellido_materno: detalle?.apellido_materno ?? "",
    celular: "",
    organizacion: detalle ? String(detalle.organizacion.id) : "",
    planta: detalle ? String(detalle.planta.id) : "",
    fecha_ingreso: detalle?.fecha_ingreso ?? "",
    puesto: detalle?.puesto ?? "",
    tipo_empleado: detalle?.tipo_empleado ?? "",
    campos: Object.fromEntries(dinamicos.map((c) => [c.codigo_interno, aTexto(detalle?.campos[c.codigo_interno])])),
    consentimiento: detalle?.consentimiento.otorgado ?? false,
  };

  const esquema = construirEsquema(dinamicos, edicion, ocultos);
  const { register, handleSubmit, setError, reset, formState } = useForm<Valores>({
    resolver: zodResolver(esquema) as unknown as Resolver<Valores>,
    defaultValues: inicial,
  });
  // Tras guardar, el detalle se vuelve a leer (nuevo ETag): se descartan los valores escritos
  // (p. ej. sensibles) y el formulario vuelve a reflejar lo guardado.
  useEffect(() => {
    reset(inicial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [etag]);
  const { errors, isSubmitting } = formState;
  const msg = (n: keyof Valores) => (errors[n] as { message?: string } | undefined)?.message;
  const msgCampo = (codigo: string) => errors.campos?.[codigo]?.message;

  const orgsVisibles = orgs.filter((o) => o.activa || o.id === detalle?.organizacion.id);
  const plantasVisibles = plantas.filter((p) => p.activa || p.id === detalle?.planta.id);

  /** Convierte los errores del servidor (por campo y por código) en errores del formulario. */
  function mostrarErrorServidor(e: unknown) {
    if (!(e instanceof ErrorApi)) return setErrorGeneral(mensajeDeError(e));
    const conocidos = new Set<string>([...Object.keys(inicial).filter((k) => k !== "campos"), ...dinamicos.map((c) => `campos.${c.codigo_interno}`)]);
    const porClave = new Map(dinamicos.map((c) => [`campos.${c.clave}`, `campos.${c.codigo_interno}`]));
    const alias: Record<string, string> = { organizacion_id: "organizacion", planta_id: "planta" };
    const huerfanos: string[] = [];
    for (const er of e.errores) {
      const nombre = alias[er.campo] ?? porClave.get(er.campo) ?? er.campo;
      if (conocidos.has(nombre)) setError(nombre as never, { type: er.codigo, message: er.mensaje });
      else huerfanos.push(er.mensaje);
    }
    if (e.codigo === "NUMERO_EMPLEADO_DUPLICADO") setError("numero_empleado", { type: e.codigo, message: e.message });
    else if (e.codigo === "CELULAR_DUPLICADO") setError("celular", { type: e.codigo, message: e.message });
    else if (e.errores.length === 0 || huerfanos.length > 0) setErrorGeneral(huerfanos[0] ?? e.message);
  }

  async function alEnviar(v: Valores) {
    setErrorGeneral(null);
    setAviso(null);
    try {
      if (!detalle) {
        const cuerpo: ColaboradorCrear = {
          numero_empleado: v.numero_empleado.trim().toUpperCase(),
          nombres: v.nombres.trim(),
          apellido_paterno: v.apellido_paterno.trim(),
          apellido_materno: v.apellido_materno.trim(),
          celular: soloDigitos(v.celular),
          organizacion_id: Number(v.organizacion),
          planta_id: Number(v.planta),
          fecha_ingreso: v.fecha_ingreso,
          puesto: v.puesto.trim(),
          tipo_empleado: v.tipo_empleado as ColaboradorCrear["tipo_empleado"],
          campos: Object.fromEntries(
            dinamicos.filter((c) => v.campos[c.codigo_interno]?.trim()).map((c) => [c.codigo_interno, convertir(c, v.campos[c.codigo_interno]!.trim())]),
          ),
          consentimiento: v.consentimiento,
        };
        await apiColaboradores.crear(cuerpo);
        await cliente.invalidateQueries({ queryKey: CLAVE_COLABORADORES });
        navegar("/colaboradores");
        return;
      }

      const cambios: ColaboradorActualizar = {};
      for (const k of ["nombres", "apellido_paterno", "apellido_materno", "puesto", "fecha_ingreso"] as const) {
        if (v[k].trim() !== inicial[k]) cambios[k] = v[k].trim();
      }
      if (v.tipo_empleado !== inicial.tipo_empleado) cambios.tipo_empleado = v.tipo_empleado as ColaboradorActualizar["tipo_empleado"];
      if (v.organizacion !== inicial.organizacion) cambios.organizacion_id = Number(v.organizacion);
      if (v.planta !== inicial.planta) cambios.planta_id = Number(v.planta);
      if (v.celular.trim()) cambios.celular = soloDigitos(v.celular);
      const cambiosCampos: Record<string, unknown> = {};
      for (const c of dinamicos) {
        const nuevo = (v.campos[c.codigo_interno] ?? "").trim();
        if (nuevo !== inicial.campos[c.codigo_interno]) cambiosCampos[c.codigo_interno] = nuevo === "" ? null : convertir(c, nuevo);
      }
      if (Object.keys(cambiosCampos).length > 0) cambios.campos = cambiosCampos;

      const cambiaConsentimiento = v.consentimiento !== inicial.consentimiento;
      if (Object.keys(cambios).length === 0 && !cambiaConsentimiento) {
        setAviso(T.sinCambios);
        return;
      }
      if (Object.keys(cambios).length > 0) await apiColaboradores.actualizar(detalle.id, cambios, etag);
      if (cambiaConsentimiento) await apiColaboradores.consentimiento(detalle.id, v.consentimiento);
      await cliente.invalidateQueries({ queryKey: CLAVE_COLABORADORES });
      setAviso(T.guardado);
    } catch (e) {
      mostrarErrorServidor(e);
    }
  }

  function fijo(f: CampoFijoDto): ReactNode {
    const base = { etiqueta: f.nombre, requerido: f.obligatorio };
    switch (f.clave) {
      case "numero_empleado":
      case "nombres":
      case "apellido_paterno":
      case "apellido_materno":
      case "puesto": {
        const k = f.clave as (typeof FIJOS_TEXTO)[number];
        return (
          <Control key={f.clave} {...base} error={msg(k)} hijo={(p) => (
            <input {...p} type="text" placeholder={T.placeholders[k]} readOnly={edicion && k === "numero_empleado"} {...register(k)} />
          )} />
        );
      }
      case "celular":
        return (
          <Control key={f.clave} {...base} requerido={!edicion} error={msg("celular")} ayuda={edicion ? T.celularOculto(detalle.celular) : undefined} hijo={(p) => (
            <input {...p} type="tel" inputMode="numeric" autoComplete="off" placeholder={T.placeholders.celular} {...register("celular")} />
          )} />
        );
      case "organizacion":
        return (
          <Control key={f.clave} {...base} error={msg("organizacion")} hijo={(p) => (
            <select {...p} {...register("organizacion")}>
              <option value="">{T.seleccionar}</option>
              {orgsVisibles.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.clave} · {o.razon_social}
                </option>
              ))}
            </select>
          )} />
        );
      case "planta":
        return (
          <Control key={f.clave} {...base} error={msg("planta")} hijo={(p) => (
            <select {...p} {...register("planta")}>
              <option value="">{T.seleccionar}</option>
              {plantasVisibles.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.nombre}
                </option>
              ))}
            </select>
          )} />
        );
      case "fecha_ingreso":
        return (
          <Control key={f.clave} {...base} error={msg("fecha_ingreso")} hijo={(p) => <input {...p} type="date" {...register("fecha_ingreso")} />} />
        );
      case "tipo_empleado":
        return (
          <Control key={f.clave} {...base} error={msg("tipo_empleado")} hijo={(p) => (
            <select {...p} {...register("tipo_empleado")}>
              <option value="">{T.seleccionar}</option>
              <option value="ADMINISTRATIVO">{tl.administrativo}</option>
              <option value="OPERATIVO">{tl.operativo}</option>
            </select>
          )} />
        );
      case "estatus":
        return (
          <Control key={f.clave} {...base} hijo={(p) => <input {...p} type="text" value={detalle?.estatus ?? "ACTIVO"} readOnly disabled />} />
        );
      default:
        return null;
    }
  }

  function dinamico(c: CampoDto): ReactNode {
    const nombre = `campos.${c.codigo_interno}` as const;
    const oculto = ocultos.has(c.codigo_interno);
    const comun = {
      etiqueta: c.nombre_campo,
      requerido: c.obligatorio && !oculto,
      sensible: c.es_sensible,
      error: msgCampo(c.codigo_interno),
      ayuda: oculto ? T.valorOculto : c.es_sensible ? T.sensibleAyuda : undefined,
    };
    const opciones = (c.opciones ?? []).filter((o) => o.activo).sort((a, b) => a.orden - b.orden);
    return (
      <Control key={c.codigo_interno} {...comun} hijo={(p) => {
        if (c.tipo_dato === "LISTA")
          return (
            <select {...p} {...register(nombre)}>
              <option value="">{T.seleccionar}</option>
              {opciones.map((o) => (
                <option key={o.id} value={o.valor}>
                  {o.etiqueta}
                </option>
              ))}
            </select>
          );
        if (c.tipo_dato === "SI_NO")
          return (
            <select {...p} {...register(nombre)}>
              <option value="">{T.seleccionar}</option>
              <option value="true">{T.si}</option>
              <option value="false">{T.no}</option>
            </select>
          );
        const tipo = c.tipo_dato === "FECHA" ? "date" : c.tipo_dato === "NUMERO" ? "number" : "text";
        return <input {...p} type={tipo} step={tipo === "number" ? "any" : undefined} autoComplete="off" {...register(nombre)} />;
      }} />
    );
  }

  return (
    <>
      {detalle && !detalle.elegible && detalle.motivo_no_elegible && (
        <div className="alerta-info" role="status">
          {T.noElegible(detalle.motivo_no_elegible)}
        </div>
      )}
      {errorGeneral && (
        <div className="alerta-error" role="alert">
          {errorGeneral}
        </div>
      )}
      {aviso && (
        <div className="alerta-info" role="status">
          {aviso}
        </div>
      )}

      <form onSubmit={handleSubmit(alEnviar)} noValidate aria-label={edicion ? T.editarTitulo : T.nuevoTitulo}>
        <section className="tarjeta col-seccion" aria-labelledby="col-fijos">
          <header>
            <h2 id="col-fijos">{T.fijos}</h2>
            <span>{T.fijosAyuda}</span>
          </header>
          <div className="col-rejilla">{fijos.map(fijo)}</div>
        </section>

        {dinamicos.length > 0 && (
          <section className="tarjeta col-seccion" aria-labelledby="col-adic">
            <header>
              <h2 id="col-adic">{T.adicionales}</h2>
              <span>{T.adicionalesAyuda}</span>
            </header>
            <div className="col-rejilla">{dinamicos.map(dinamico)}</div>
          </section>
        )}

        <section className="tarjeta col-consentimiento">
          <label>
            <input type="checkbox" {...register("consentimiento")} /> {T.consentimiento}
          </label>
          <small>{T.consentimientoAyuda}</small>
        </section>

        <div className="col-cabecera-botones">
          <Link className="btn btn-contorno" to="/colaboradores">
            {T.cancelar}
          </Link>
          <button type="submit" className="btn btn-primario" disabled={isSubmitting}>
            {edicion ? T.guardarCambios : T.guardarNuevo}
          </button>
        </div>
      </form>

      {detalle && <CicloDeVida detalle={detalle} alCambiar={() => cliente.invalidateQueries({ queryKey: CLAVE_COLABORADORES })} />}
    </>
  );
}

// ---------------------------------------------------------------- baja y reactivación

function CicloDeVida({ detalle, alCambiar }: { detalle: ColaboradorDetalle; alCambiar(): Promise<unknown> }) {
  const [abierto, setAbierto] = useState(false);
  const [fecha, setFecha] = useState("");
  const [errorFecha, setErrorFecha] = useState<string | null>(null);
  const [consentimiento, setConsentimiento] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const enBaja = detalle.estatus === "BAJA";

  async function ejecutar(accion: () => Promise<unknown>) {
    setError(null);
    try {
      await accion();
      setAbierto(false);
      await alCambiar();
    } catch (e) {
      setError(mensajeDeError(e));
    }
  }

  function darDeBaja() {
    if (!fecha) return setErrorFecha(T.baja.fechaRequerida);
    setErrorFecha(null);
    void ejecutar(() => apiColaboradores.baja(detalle.id, fecha));
  }

  function reactivar() {
    // Con consentimiento vigente no hace falta confirmarlo de nuevo.
    void ejecutar(() => apiColaboradores.reactivar(detalle.id, detalle.consentimiento.vigente ? false : consentimiento));
  }

  return (
    <section className="tarjeta col-ciclo" aria-label={enBaja ? T.reactivar.titulo : T.baja.titulo}>
      {error && (
        <div className="alerta-error" role="alert">
          {error}
        </div>
      )}
      {enBaja && <p>{T.baja.estado(detalle.fecha_baja ? fechaCivil(detalle.fecha_baja) : null)}</p>}
      {!abierto && (
        <div className="col-fila">
          {enBaja ? (
            <button
              type="button"
              className="btn btn-contorno"
              onClick={() => (detalle.consentimiento.vigente ? reactivar() : setAbierto(true))}
            >
              {T.reactivar.boton}
            </button>
          ) : (
            <button type="button" className="btn btn-peligro" onClick={() => setAbierto(true)}>
              {T.baja.boton}
            </button>
          )}
        </div>
      )}
      {abierto && !enBaja && (
        <div className="col-fila">
          <Control etiqueta={T.baja.fecha} requerido error={errorFecha ?? undefined} hijo={(p) => (
            <input {...p} type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
          )} />
          <button type="button" className="btn btn-peligro" onClick={darDeBaja}>
            {T.baja.confirmar}
          </button>
          <button type="button" className="btn" onClick={() => setAbierto(false)}>
            {T.baja.cancelar}
          </button>
        </div>
      )}
      {abierto && enBaja && (
        <div className="col-fila">
          <p>{T.reactivar.sinConsentimiento}</p>
          <label>
            <input type="checkbox" checked={consentimiento} onChange={(e) => setConsentimiento(e.target.checked)} /> {T.reactivar.casilla}
          </label>
          <button type="button" className="btn btn-primario" onClick={reactivar}>
            {T.reactivar.confirmar}
          </button>
          <button type="button" className="btn" onClick={() => setAbierto(false)}>
            {T.reactivar.cancelar}
          </button>
        </div>
      )}
    </section>
  );
}
