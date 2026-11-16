import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { apiCampos } from "@/features/campos/api";
import { apiOrganizaciones, apiPlantas } from "@/features/organizaciones/api";
import { ErrorApi } from "@/shared/errores";
import { Campo } from "@/shared/ui/Campo";
import {
  apiAudiencias,
  apiNotificaciones,
  apiPlantillasMensaje,
  CLAVES,
  type Confirmar,
  type Notificacion,
  type NotificacionCrear,
  type Revision,
  type VariableAsignada,
} from "../api";
import { Dialogo, esCodigo, HORARIO, mensajeError } from "../comun";
import { aInstanteMexico, dentroDeHorario } from "../formato";
import { t } from "../textos";
import { Audiencia, type ColaboradorElegido, type Modo } from "./Audiencia";
import { aCriterios, construirCatalogo, desdeCriterios, grupoInicial, rutasDe, type Grupo } from "./criterios";
import { Mensaje, variableVacia, type VariableUI } from "./Mensaje";
import { Resumen, type Cuando } from "./Resumen";
import "../notificaciones.css";

/** Primer mensaje cuyo campo es la ruta o cuelga de ella (`variables.1` abarca `variables.1.campo`). */
function mensajeDe(errores: Record<string, string>, ruta: string, exacta = false): string | undefined {
  const k = Object.keys(errores).find((c) => c === ruta || (!exacta && c.startsWith(`${ruta}.`)));
  return k ? errores[k] : undefined;
}

function variablesDeApi(v: Record<string, unknown>): Record<string, VariableUI> {
  const r: Record<string, VariableUI> = {};
  for (const [n, x] of Object.entries(v)) {
    const a = x as VariableAsignada;
    r[n] = { origen: a.origen, campo: a.campo ?? "", valor: a.valor ?? "" };
  }
  return r;
}

/** Nueva notificación (cv1_09) y edición de un borrador. */
export function NuevaNotificacion() {
  const { id: idParam } = useParams();
  const idInicial = idParam ? Number(idParam) : null;
  const navegar = useNavigate();
  const qc = useQueryClient();

  // Catálogos
  const campos = useQuery({ queryKey: ["notificaciones", "catalogo", "campos"], queryFn: () => apiCampos.listar("activos") });
  const organizaciones = useQuery({ queryKey: ["notificaciones", "catalogo", "organizaciones"], queryFn: () => apiOrganizaciones.listar(true) });
  const plantas = useQuery({ queryKey: ["notificaciones", "catalogo", "plantas"], queryFn: () => apiPlantas.listar(true) });
  const aprobadas = useQuery({ queryKey: [...CLAVES.plantillas, "aprobadas"], queryFn: () => apiPlantillasMensaje.listar("APROBADA") });
  const grupos = useQuery({ queryKey: ["notificaciones", "audiencias"], queryFn: apiAudiencias.listar });
  const existente = useQuery({
    queryKey: idInicial ? CLAVES.detalle(idInicial) : ["notificaciones", "detalle", "nueva"],
    queryFn: () => apiNotificaciones.detalle(idInicial as number),
    enabled: idInicial !== null,
  });

  const dinamicos = useMemo(() => (campos.data?.dinamicos ?? []).filter((c) => c.activo && !c.es_sensible), [campos.data]);
  const catalogo = useMemo(
    () =>
      construirCatalogo(
        (organizaciones.data ?? []).map((o) => ({ id: o.id, nombre: o.razon_social })),
        (plantas.data ?? []).map((p) => ({ id: p.id, nombre: p.nombre })),
        dinamicos,
      ),
    [organizaciones.data, plantas.data, dinamicos],
  );

  // Formulario
  const [notificacionId, setNotificacionId] = useState<number | null>(idInicial);
  const [titulo, setTitulo] = useState("");
  const [modo, setModo] = useState<Modo>("CRITERIOS");
  const [raiz, setRaiz] = useState<Grupo>(grupoInicial);
  const [colaborador, setColaborador] = useState<ColaboradorElegido | null>(null);
  const [audienciaId, setAudienciaId] = useState("");
  const [plantillaId, setPlantillaId] = useState("");
  const [variables, setVariables] = useState<Record<string, VariableUI>>({});
  const [respaldo, setRespaldo] = useState(false);
  const [cuando, setCuando] = useState<Cuando>("AHORA");
  const [fecha, setFecha] = useState("");
  const [hora, setHora] = useState("");

  // Resultado y mensajes
  const [revision, setRevision] = useState<Revision | null>(null);
  const [obsoleta, setObsoleta] = useState(false);
  const [errores, setErrores] = useState<Record<string, string>>({});
  const [erroresCrit, setErroresCrit] = useState<Map<string, string>>(new Map());
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [confirmandoFuera, setConfirmandoFuera] = useState(false);

  // Hidratar el borrador una sola vez.
  const hidratado = useRef(false);
  useEffect(() => {
    const n: Notificacion | undefined = existente.data;
    if (!n || hidratado.current) return;
    hidratado.current = true;
    setTitulo(n.titulo);
    setModo(n.modo);
    if (n.modo === "CRITERIOS" && n.criterios) setRaiz(desdeCriterios(n.criterios));
    if (n.modo === "INDIVIDUAL" && n.colaborador_id) setColaborador({ id: n.colaborador_id, nombre: null });
    if (n.modo === "GRUPO" && n.audiencia_id) setAudienciaId(String(n.audiencia_id));
    if (n.plantilla) setPlantillaId(String(n.plantilla.id));
    setVariables(variablesDeApi(n.variables));
    setRespaldo(n.respaldo_correo);
  }, [existente.data]);

  const plantillas = aprobadas.data?.items ?? [];
  const plantilla = plantillas.find((p) => String(p.id) === plantillaId);

  const cambio = () => {
    setErrores({});
    setErroresCrit(new Map());
    setErrorGeneral(null);
    setAviso(null);
    setObsoleta(true);
  };

  function manejar(e: unknown) {
    if (e instanceof ErrorApi && e.errores.length > 0) {
      const m: Record<string, string> = {};
      for (const x of e.errores) if (!(x.campo in m)) m[x.campo] = x.mensaje;
      setErrores(m);
      const general = e.errores.some((x) => ["notificacion", "modo"].includes(x.campo.split(".")[0]!));
      setErrorGeneral(general ? mensajeError(e, t.nueva.errores) : null);
      return;
    }
    setErrorGeneral(mensajeError(e, t.nueva.errores));
  }

  async function ejecutar(fn: () => Promise<void>) {
    setOcupado(true);
    setErrorGeneral(null);
    try {
      await fn();
    } catch (e) {
      manejar(e);
    } finally {
      setOcupado(false);
    }
  }

  function construir(): NotificacionCrear | null {
    const e: Record<string, string> = {};
    let crit = new Map<string, string>();
    if (!titulo.trim()) e.titulo = t.nueva.tituloRequerido;
    if (!plantilla) e.plantilla_mensaje_id = t.nueva.plantillaRequerida;
    const vars: Record<string, VariableAsignada> = {};
    for (let i = 1; i <= (plantilla?.cantidad_variables ?? 0); i++) {
      const v = variables[String(i)] ?? variableVacia();
      if (v.origen === "COLABORADOR") {
        if (!v.campo) e[`variables.${i}`] = t.nueva.campoRequerido;
        else vars[String(i)] = { origen: "COLABORADOR", campo: v.campo };
      } else if (!v.valor.trim()) e[`variables.${i}`] = t.nueva.valorRequerido;
      else vars[String(i)] = { origen: "FIJO", valor: v.valor.trim() };
    }
    let audiencia: Pick<NotificacionCrear, "criterios" | "colaborador_id" | "audiencia_id"> = {};
    if (modo === "CRITERIOS") {
      const r = aCriterios(raiz, catalogo);
      crit = r.errores;
      if (r.criterios) audiencia = { criterios: r.criterios };
    } else if (modo === "INDIVIDUAL") {
      if (!colaborador) e.colaborador_id = t.nueva.individualRequerido;
      else audiencia = { colaborador_id: colaborador.id };
    } else if (!audienciaId) e.audiencia_id = t.nueva.grupoRequerido;
    else audiencia = { audiencia_id: Number(audienciaId) };

    if (Object.keys(e).length > 0 || crit.size > 0) {
      setErrores(e);
      setErroresCrit(crit);
      return null;
    }
    return {
      titulo: titulo.trim(),
      modo,
      plantilla_mensaje_id: Number(plantillaId),
      variables: vars,
      respaldo_correo: respaldo,
      zona_horaria: HORARIO.zona,
      ...audiencia,
    };
  }

  /** Crea o actualiza el borrador. Devuelve su id, o `null` si hay errores en pantalla. */
  async function guardar(): Promise<number | null> {
    const cuerpo = construir();
    if (!cuerpo) return null;
    const n = notificacionId === null ? await apiNotificaciones.crear(cuerpo) : await apiNotificaciones.actualizar(notificacionId, cuerpo);
    setNotificacionId(n.id);
    void qc.invalidateQueries({ queryKey: CLAVES.listado });
    return n.id;
  }

  const guardarBorrador = () =>
    ejecutar(async () => {
      if ((await guardar()) !== null) {
        // El servidor invalida la revisión al cambiar la audiencia: hay que revisar de nuevo.
        setObsoleta(true);
        setAviso(t.nueva.guardado);
      }
    });

  const revisar = () =>
    ejecutar(async () => {
      const id = await guardar();
      if (id === null) return;
      const r = await apiNotificaciones.revisar(id);
      setRevision(r);
      setObsoleta(false);
    });

  function programacion(): string | null {
    if (!fecha || !hora) {
      setErrores({ programada_para: t.nueva.fechaRequerida });
      return null;
    }
    if (!dentroDeHorario(hora, HORARIO.inicio, HORARIO.fin)) {
      setErrores({ programada_para: t.nueva.programacionFueraHorario });
      return null;
    }
    const instante = aInstanteMexico(fecha, hora);
    if (new Date(instante).getTime() <= Date.now()) {
      setErrores({ programada_para: t.nueva.programacionPasada });
      return null;
    }
    return instante;
  }

  const enviar = (confirmarFuera: boolean) =>
    ejecutar(async () => {
      if (notificacionId === null || !revision || obsoleta) return;
      const cuerpo: Confirmar = { modo_envio: cuando, respaldo_correo: respaldo, confirmar_fuera_horario: confirmarFuera };
      if (cuando === "PROGRAMAR") {
        const instante = programacion();
        if (!instante) return;
        cuerpo.programada_para = instante;
      }
      try {
        await apiNotificaciones.confirmar(notificacionId, cuerpo);
      } catch (e) {
        if (esCodigo(e, "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION")) {
          setConfirmandoFuera(true);
          return;
        }
        throw e;
      }
      setConfirmandoFuera(false);
      void qc.invalidateQueries({ queryKey: CLAVES.listado });
      void qc.invalidateQueries({ queryKey: CLAVES.indicadores });
      navegar(`/notificaciones/${notificacionId}`);
    });

  // Una notificación que ya no es borrador no se edita: se ve su detalle.
  if (existente.data && existente.data.estado !== "BORRADOR") return <Navigate to={`/notificaciones/${existente.data.id}`} replace />;

  const rutas = rutasDe(raiz);
  const erroresCriterios = new Map(erroresCrit);
  const grupoClaves = new Set<string>();
  const marcar = (g: Grupo) => {
    grupoClaves.add(g.clave);
    g.items.forEach((i) => "items" in i && marcar(i));
  };
  marcar(raiz);
  for (const [clave, ruta] of rutas) {
    // Un grupo solo muestra el error de su propia ruta; el de un criterio, el de ese criterio.
    const m = mensajeDe(errores, ruta, grupoClaves.has(clave));
    if (m && !erroresCriterios.has(clave)) erroresCriterios.set(clave, m);
  }
  const destinatarios = revision ? revision.total_seleccionados - revision.total_excluidos : 0;
  const cargandoCatalogos = campos.isPending || organizaciones.isPending || plantas.isPending || aprobadas.isPending;
  const falloCatalogos = campos.isError || organizaciones.isError || plantas.isError || aprobadas.isError;
  const editando = idInicial !== null;

  return (
    <div className="not">
      <div className="encabezado">
        <div>
          <h1>{editando ? t.nueva.tituloEdicion : t.nueva.titulo}</h1>
          <nav aria-label="Ruta de navegación" className="not-migas">
            <Link to="/notificaciones">{t.migas.notificaciones}</Link> / {editando ? t.nueva.tituloEdicion : t.migas.nueva}
          </nav>
        </div>
        <div className="not-acciones-cabecera">
          <button type="button" className="btn btn-contorno" disabled={ocupado} onClick={() => void guardarBorrador()}>
            {t.nueva.guardarBorrador}
          </button>
          <button type="button" className="btn btn-primario" disabled={ocupado} onClick={() => void revisar()}>
            {t.nueva.revisarYEnviar}
          </button>
        </div>
      </div>

      {errorGeneral && (
        <p className="alerta-error" role="alert">
          {errorGeneral}
        </p>
      )}
      {aviso && (
        <p className="alerta-info" role="status">
          {aviso}
        </p>
      )}
      {falloCatalogos && (
        <p className="alerta-error" role="alert">
          {t.errorCarga}
        </p>
      )}
      {cargandoCatalogos && !falloCatalogos && <p role="status">{t.cargando}</p>}

      <div className="not-nueva">
        <div className="not-columna">
          <section className="tarjeta not-seccion">
            <Campo
              etiqueta={t.nueva.tituloEnvio}
              value={titulo}
              maxLength={150}
              error={errores.titulo}
              onChange={(e) => {
                setTitulo(e.target.value);
                cambio();
              }}
            />
          </section>
          <Audiencia
            modo={modo}
            alCambiarModo={(m) => {
              setModo(m);
              cambio();
            }}
            raiz={raiz}
            alCambiarRaiz={(g) => {
              setRaiz(g);
              cambio();
            }}
            catalogo={catalogo}
            erroresCriterios={erroresCriterios}
            grupos={grupos.data?.items ?? []}
            audienciaId={audienciaId}
            alCambiarAudiencia={(v) => {
              setAudienciaId(v);
              cambio();
            }}
            colaborador={colaborador}
            alElegirColaborador={(c) => {
              setColaborador(c);
              cambio();
            }}
            errorAudiencia={errores.audiencia_id}
            errorColaborador={errores.colaborador_id}
          />
          <Mensaje
            plantillas={plantillas}
            plantillaId={plantillaId}
            alElegirPlantilla={(id) => {
              setPlantillaId(id);
              setVariables({});
              cambio();
            }}
            variables={variables}
            alCambiarVariable={(n, v) => {
              setVariables((a) => ({ ...a, [n]: v }));
              cambio();
            }}
            camposDinamicos={dinamicos}
            errores={errores}
          />
        </div>

        <Resumen
          revision={revision}
          obsoleta={obsoleta}
          destinatarios={destinatarios}
          cuando={cuando}
          alCambiarCuando={(c) => {
            setCuando(c);
            setErrores((e) => ({ ...e, programada_para: "" }));
          }}
          fecha={fecha}
          hora={hora}
          alCambiarFecha={(v) => {
            setFecha(v);
            setErrores((e) => ({ ...e, programada_para: "" }));
          }}
          alCambiarHora={(v) => {
            setHora(v);
            setErrores((e) => ({ ...e, programada_para: "" }));
          }}
          errorProgramacion={errores.programada_para || undefined}
          respaldo={respaldo}
          alCambiarRespaldo={setRespaldo}
          ocupado={ocupado}
          alGuardar={() => void guardarBorrador()}
          alEnviar={() => void enviar(false)}
        />
      </div>

      {confirmandoFuera && (
        <Dialogo
          titulo={t.nueva.fueraHorarioTitulo}
          alCerrar={() => setConfirmandoFuera(false)}
          acciones={
            <>
              <button type="button" className="btn btn-contorno" onClick={() => setConfirmandoFuera(false)}>
                {t.cancelar}
              </button>
              <button type="button" className="btn btn-primario" disabled={ocupado} onClick={() => void enviar(true)}>
                {t.nueva.fueraHorarioConfirmar}
              </button>
            </>
          }
        >
          <p>{t.nueva.fueraHorario(HORARIO.inicio, HORARIO.fin)}</p>
        </Dialogo>
      )}
    </div>
  );
}
