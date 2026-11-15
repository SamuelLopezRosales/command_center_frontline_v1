import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { aplicarErroresDeCampo, mensajeDeError } from "@/shared/errores";
import { Campo } from "@/shared/ui/Campo";
import { CLAVE_ORGANIZACIONES, apiOrganizaciones, subirAS3, type Organizacion } from "./api";
import { textos as t } from "./textos";

const T = t.org;
const opcional = z.string().trim();
const crearEsquema = (edicion: boolean) =>
  z.object({
  clave: edicion ? z.string().trim() : z.string().trim().min(1, t.requerido),
  razon_social: z.string().trim().min(1, t.requerido),
  rfc: opcional.refine((v) => v === "" || v.length === 12 || v.length === 13, T.rfcInvalido),
  registro_patronal: opcional,
  domicilio_fiscal: opcional,
  ciudad: opcional,
  nombre_firmante: opcional,
  cargo_firmante: opcional,
  correo_firmante: opcional.refine((v) => v === "" || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v), T.correoInvalido),
  activa: z.boolean(),
});
type Valores = z.infer<ReturnType<typeof crearEsquema>>;

const orNull = (v: string) => (v === "" ? null : v);

export function Organizaciones() {
  const [seleccion, setSeleccion] = useState<number | "nueva" | null>(null);
  const consulta = useQuery({ queryKey: [...CLAVE_ORGANIZACIONES], queryFn: () => apiOrganizaciones.listar(false) });
  const orgs = consulta.data ?? [];
  const actual = typeof seleccion === "number" ? (orgs.find((o) => o.id === seleccion) ?? null) : null;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <button className="btn btn-primario" onClick={() => setSeleccion("nueva")}>
          {T.nueva}
        </button>
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
        <div className={`org-cuerpo${seleccion === null ? " sin-panel" : ""}`}>
          <section className="tarjeta org-tabla" aria-label={t.pestanas.organizaciones}>
            <table className="tabla">
              <thead>
                <tr>
                  <th>{T.columnas.clave}</th>
                  <th>{T.columnas.razon}</th>
                  <th>{T.columnas.rfc}</th>
                  <th>{T.columnas.ciudad}</th>
                  <th>{T.columnas.logotipo}</th>
                  <th>{T.columnas.estado}</th>
                  <th>
                    <span className="sr-solo">{t.editar}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {orgs.map((o) => (
                  <tr key={o.id}>
                    <td>{o.clave}</td>
                    <td>{o.razon_social}</td>
                    <td>{o.rfc ?? "—"}</td>
                    <td>{o.ciudad ?? "—"}</td>
                    <td>{o.tiene_logotipo ? T.conLogotipo : T.sinLogotipo}</td>
                    <td>
                      <span className={`insignia ${o.activa ? "ok" : "neutro"}`}>{o.activa ? t.activa : t.inactiva}</span>
                    </td>
                    <td>
                      <button className="btn-enlace" aria-label={`${t.editar} ${o.clave}`} onClick={() => setSeleccion(o.id)}>
                        {t.editar}
                      </button>
                    </td>
                  </tr>
                ))}
                {orgs.length === 0 && (
                  <tr>
                    <td colSpan={7}>{T.vacio}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
          {seleccion === "nueva" && <PanelOrganizacion key="nueva" org={null} onCerrar={() => setSeleccion(null)} onGuardada={(o) => setSeleccion(o.id)} />}
          {actual && <PanelOrganizacion key={actual.id} org={actual} onCerrar={() => setSeleccion(null)} onGuardada={() => undefined} />}
        </div>
      )}
    </>
  );
}

function PanelOrganizacion({ org, onCerrar, onGuardada }: { org: Organizacion | null; onCerrar(): void; onGuardada(o: Organizacion): void }) {
  const cliente = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const { register, handleSubmit, setError: setErrorCampo, formState } = useForm<Valores>({
    resolver: zodResolver(crearEsquema(org !== null)),
    defaultValues: {
      clave: org?.clave ?? "",
      razon_social: org?.razon_social ?? "",
      rfc: org?.rfc ?? "",
      registro_patronal: org?.registro_patronal ?? "",
      domicilio_fiscal: org?.domicilio_fiscal ?? "",
      ciudad: org?.ciudad ?? "",
      nombre_firmante: org?.nombre_firmante ?? "",
      cargo_firmante: org?.cargo_firmante ?? "",
      correo_firmante: org?.correo_firmante ?? "",
      activa: org?.activa ?? true,
    },
  });
  const { errors, isSubmitting } = formState;
  const refrescar = () => cliente.invalidateQueries({ queryKey: CLAVE_ORGANIZACIONES });

  async function alEnviar(v: Valores) {
    setError(null);
    setAviso(null);
    try {
      let guardada: Organizacion;
      if (!org) {
        guardada = await apiOrganizaciones.crear({
          clave: v.clave,
          razon_social: v.razon_social,
          rfc: orNull(v.rfc),
          registro_patronal: orNull(v.registro_patronal),
          domicilio_fiscal: orNull(v.domicilio_fiscal),
          ciudad: orNull(v.ciudad),
          nombre_firmante: orNull(v.nombre_firmante),
          cargo_firmante: orNull(v.cargo_firmante),
          correo_firmante: orNull(v.correo_firmante),
        });
      } else {
        guardada = await apiOrganizaciones.actualizar(org.id, {
          razon_social: v.razon_social,
          rfc: orNull(v.rfc),
          registro_patronal: orNull(v.registro_patronal),
          domicilio_fiscal: orNull(v.domicilio_fiscal),
          ciudad: orNull(v.ciudad),
          nombre_firmante: orNull(v.nombre_firmante),
          cargo_firmante: orNull(v.cargo_firmante),
          correo_firmante: orNull(v.correo_firmante),
          activa: v.activa,
        });
      }
      setAviso(T.guardada);
      await refrescar();
      onGuardada(guardada);
    } catch (e) {
      if (!aplicarErroresDeCampo(e, setErrorCampo)) setError(mensajeDeError(e));
    }
  }

  async function alternarActiva() {
    if (!org) return;
    setError(null);
    try {
      await apiOrganizaciones.actualizar(org.id, { activa: !org.activa });
      await refrescar();
    } catch (e) {
      setError(mensajeDeError(e));
    }
  }

  return (
    <aside className="tarjeta org-panel" aria-label={org ? T.panelEditar : T.panelNueva}>
      <h2>{org ? T.panelEditar : T.panelNueva}</h2>
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
        <Campo etiqueta={T.clave} error={errors.clave?.message} ayuda={T.claveAyuda} disabled={!!org} {...register("clave")} />
        <Campo etiqueta={T.razon} error={errors.razon_social?.message} {...register("razon_social")} />
        <Campo etiqueta={T.rfc} error={errors.rfc?.message} maxLength={13} {...register("rfc")} />
        <Campo etiqueta={T.registroPatronal} error={errors.registro_patronal?.message} {...register("registro_patronal")} />
        <Campo etiqueta={T.domicilio} error={errors.domicilio_fiscal?.message} {...register("domicilio_fiscal")} />
        <Campo etiqueta={T.ciudad} error={errors.ciudad?.message} {...register("ciudad")} />
        <Campo etiqueta={T.firmante} error={errors.nombre_firmante?.message} {...register("nombre_firmante")} />
        <Campo etiqueta={T.cargoFirmante} error={errors.cargo_firmante?.message} {...register("cargo_firmante")} />
        <Campo etiqueta={T.correoFirmante} error={errors.correo_firmante?.message} {...register("correo_firmante")} />
        {org && (
          <label className="org-activa" style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <input type="checkbox" {...register("activa")} /> {T.activa}
          </label>
        )}
        <div className="org-acciones">
          {org && (
            <button type="button" className="btn btn-peligro" onClick={() => void alternarActiva()}>
              {org.activa ? T.desactivar : T.activar}
            </button>
          )}
          <button type="submit" className="btn btn-primario" disabled={isSubmitting}>
            {T.guardar}
          </button>
        </div>
        <div className="org-acciones">
          <button type="button" className="btn" onClick={onCerrar}>
            {t.cerrar}
          </button>
        </div>
      </form>
      {org && <Logotipo org={org} alSubir={refrescar} />}
    </aside>
  );
}

const TIPOS_LOGOTIPO = ["image/png", "image/jpeg"];
const MAX_LOGOTIPO = 1024 * 1024;

function Logotipo({ org, alSubir }: { org: Organizacion; alSubir(): Promise<unknown> }) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [subiendo, setSubiendo] = useState(false);

  function elegir(f: File | null) {
    setOk(false);
    setError(null);
    if (f && !TIPOS_LOGOTIPO.includes(f.type)) {
      setArchivo(null);
      return setError(T.logotipoTipo);
    }
    if (f && f.size > MAX_LOGOTIPO) {
      setArchivo(null);
      return setError(T.logotipoTamano);
    }
    setArchivo(f);
  }

  async function subir() {
    if (!archivo) return setError(T.logotipoElige);
    setSubiendo(true);
    setError(null);
    try {
      const url = await apiOrganizaciones.solicitarLogotipo(org.id, archivo.type, archivo.size);
      await subirAS3(url.url, archivo, archivo.type);
      await apiOrganizaciones.confirmarLogotipo(org.id, url.s3_key);
      setOk(true);
      setArchivo(null);
      await alSubir();
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setSubiendo(false);
    }
  }

  return (
    <section className="org-logotipo" aria-label={T.logotipo}>
      <h3>{T.logotipo}</h3>
      <p className="ayuda">{org.tiene_logotipo ? T.conLogotipo : T.sinLogotipo} · {T.logotipoAyuda}</p>
      <div className="campo">
        <label htmlFor={`logo-${org.id}`}>{T.logotipoArchivo}</label>
        <input id={`logo-${org.id}`} type="file" accept="image/png,image/jpeg" onChange={(e) => elegir(e.target.files?.[0] ?? null)} />
      </div>
      {error && (
        <div className="alerta-error" role="alert">
          {error}
        </div>
      )}
      {ok && (
        <div className="alerta-info" role="status">
          {T.logotipoOk}
        </div>
      )}
      <button type="button" className="btn btn-contorno" disabled={subiendo} onClick={() => void subir()}>
        {T.logotipoSubir}
      </button>
    </section>
  );
}
