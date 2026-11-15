import type { Editor } from "@tiptap/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  actualizarPlantilla,
  guardarBorrador,
  leerBorrador,
  leerVersion,
  listarVariables,
  listarVersiones,
  obtenerPlantilla,
  publicar,
  restaurarVersion,
  validarBorrador,
  type Contenido,
  type Plantilla,
  type ResultadoValidacion,
  type Variable,
} from "../api";
import { Dialogo } from "../Dialogo";
import { fechaMedia } from "../formato";
import { t } from "../textos";
import "../constancias.css";
import { ErrorApi, mensajeDeError } from "@/shared/errores";
import { EditorVisual, nombresSensibles } from "./EditorVisual";
import { ListaVersiones } from "./ListaVersiones";
import { PanelValidacion } from "./PanelValidacion";
import { docAContenido, variablesDelDoc } from "./serializar";
import { VistaPrevia } from "./VistaPrevia";

interface Borrador {
  contenido: Contenido;
  etag: string | null;
  /** false si todavía no hay borrador guardado (se parte de la última versión o de una hoja vacía). */
  existe: boolean;
  desdeVersion: boolean;
}

const VACIO: Contenido = { esquema: 1, bloques: [] };

async function cargarBorrador(id: number, versionPublicada: number | null): Promise<Borrador> {
  try {
    const { datos, etag } = await leerBorrador(id);
    return { contenido: datos.contenido, etag, existe: true, desdeVersion: false };
  } catch (e) {
    if (!(e instanceof ErrorApi) || e.status !== 404) throw e;
    if (versionPublicada) {
      const v = await leerVersion(id, versionPublicada);
      return { contenido: v.contenido, etag: null, existe: false, desdeVersion: true };
    }
    return { contenido: VACIO, etag: null, existe: false, desdeVersion: false };
  }
}

/** Editor visual de una plantilla (cv1_06). Carga plantilla, variables y borrador. */
export function EditorPlantilla() {
  const id = Number(useParams().id);
  const plantilla = useQuery({ queryKey: ["constancias", "plantilla", id], queryFn: () => obtenerPlantilla(id), enabled: Number.isFinite(id) });
  const variables = useQuery({ queryKey: ["constancias", "variables"], queryFn: listarVariables });
  const borrador = useQuery({
    queryKey: ["constancias", "borrador", id],
    queryFn: () => cargarBorrador(id, plantilla.data?.version ?? null),
    enabled: plantilla.isSuccess,
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });

  const error = plantilla.error ?? variables.error ?? borrador.error;
  if (error) {
    return (
      <div role="alert" className="alerta-error">
        {mensajeDeError(error)}{" "}
        <Link to="/constancias">{t.editor.volver}</Link>
      </div>
    );
  }
  if (!plantilla.data || !variables.data || !borrador.data) return <p role="status">{t.cargando}</p>;

  return (
    <EditorCargado
      // Al recargar el borrador (tras un conflicto) el editor se crea de nuevo.
      key={borrador.dataUpdatedAt}
      plantilla={plantilla.data}
      variables={variables.data}
      borrador={borrador.data}
      recargar={() => void borrador.refetch()}
    />
  );
}

interface PropsCargado {
  plantilla: Plantilla;
  variables: Variable[];
  borrador: Borrador;
  recargar: () => void;
}

type Aviso = { tipo: "ok" | "error"; texto: string } | null;

function EditorCargado({ plantilla, variables, borrador, recargar }: PropsCargado) {
  const id = plantilla.id;
  const qc = useQueryClient();
  const editorRef = useRef<Editor | null>(null);
  const etagRef = useRef<string | null>(borrador.etag);
  const [nombre, setNombre] = useState(plantilla.nombre);
  const [sucio, setSucio] = useState(!borrador.existe);
  const [guardando, setGuardando] = useState(false);
  const [publicando, setPublicando] = useState(false);
  const [aviso, setAviso] = useState<Aviso>(null);
  const [conflicto, setConflicto] = useState(false);
  const [validacion, setValidacion] = useState<ResultadoValidacion | null>(null);
  const [validando, setValidando] = useState(false);
  const [errorValidacion, setErrorValidacion] = useState<string | null>(null);
  const [sensiblesAConfirmar, setSensiblesAConfirmar] = useState<string[] | null>(null);
  const [restaurando, setRestaurando] = useState<number | null>(null);

  const versiones = useQuery({ queryKey: ["constancias", "versiones", id], queryFn: () => listarVersiones(id) });
  const catalogoSensibles = nombresSensibles(variables);
  const alCrear = useCallback((e: Editor) => {
    editorRef.current = e;
  }, []);
  const marcarSucio = useCallback(() => setSucio(true), []);

  const refrescar = () => {
    void qc.invalidateQueries({ queryKey: ["constancias", "plantilla", id] });
    void qc.invalidateQueries({ queryKey: ["constancias", "versiones", id] });
    void qc.invalidateQueries({ queryKey: ["constancias", "plantillas"] });
  };

  async function validar() {
    setValidando(true);
    setErrorValidacion(null);
    try {
      setValidacion(await validarBorrador(id));
    } catch (e) {
      setErrorValidacion(mensajeDeError(e) || t.validacion.errorValidar);
    } finally {
      setValidando(false);
    }
  }

  async function guardar(): Promise<boolean> {
    const ed = editorRef.current;
    const nombreLimpio = nombre.trim();
    if (!ed) return false;
    if (!nombreLimpio) {
      setAviso({ tipo: "error", texto: t.listado.nombreRequerido });
      return false;
    }
    setGuardando(true);
    setAviso(null);
    try {
      if (nombreLimpio !== plantilla.nombre) await actualizarPlantilla(id, { nombre: nombreLimpio });
      const { etag } = await guardarBorrador(id, docAContenido(ed.getJSON(), borrador.contenido.pagina), etagRef.current);
      etagRef.current = etag;
      setSucio(false);
      setConflicto(false);
      setAviso({ tipo: "ok", texto: t.editor.guardado });
      refrescar();
      void validar();
      return true;
    } catch (e) {
      if (e instanceof ErrorApi && (e.status === 412 || e.status === 428)) setConflicto(true);
      else setAviso({ tipo: "error", texto: mensajeDeError(e) });
      return false;
    } finally {
      setGuardando(false);
    }
  }

  /** Variables sensibles que el documento usa, según el catálogo. */
  function sensiblesDelDocumento(): string[] {
    const usadas = editorRef.current ? variablesDelDoc(editorRef.current.getJSON()) : [];
    return usadas.filter((v) => catalogoSensibles.has(v));
  }

  async function publicarVersion(confirmar: boolean) {
    if (!confirmar && sucio && !(await guardar())) return;
    setPublicando(true);
    setAviso(null);
    try {
      const v = await publicar(id, confirmar);
      setSensiblesAConfirmar(null);
      setAviso({ tipo: "ok", texto: t.editor.publicado(v.numero) });
      refrescar();
    } catch (e) {
      if (e instanceof ErrorApi && e.codigo === "PLANTILLA_SENSIBLES_REQUIERE_CONFIRMACION") {
        setSensiblesAConfirmar(sensiblesDelDocumento());
      } else {
        setSensiblesAConfirmar(null);
        setAviso({ tipo: "error", texto: mensajeDeError(e) });
        if (e instanceof ErrorApi && e.codigo === "PLANTILLA_VARIABLE_INVALIDA") void validar();
      }
    } finally {
      setPublicando(false);
    }
  }

  async function restaurar(numero: number) {
    setRestaurando(numero);
    setAviso(null);
    try {
      const nueva = await restaurarVersion(id, numero);
      setAviso({ tipo: "ok", texto: t.versiones.restaurada(numero, nueva.numero) });
      refrescar();
    } catch (e) {
      setAviso({ tipo: "error", texto: mensajeDeError(e) || t.versiones.errorRestaurar });
    } finally {
      setRestaurando(null);
    }
  }

  const vigente = versiones.data?.find((v) => v.numero === plantilla.version);
  const siguiente = (plantilla.version ?? 0) + 1;

  return (
    <div className="ed-pantalla">
      <header className="ed-superior">
        <Link to="/constancias" className="ed-volver">
          {t.editor.volver}
        </Link>
        <input
          className="ed-nombre"
          aria-label={t.editor.nombre}
          value={nombre}
          maxLength={120}
          onChange={(e) => {
            setNombre(e.target.value);
            setSucio(true);
          }}
        />
        <span className="ed-estado">
          {t.editor.estadoBorrador(plantilla.version, vigente ? fechaMedia(vigente.fecha_creacion) : null)}
          {sucio && <strong className="ed-sucio"> · {t.editor.sinGuardar}</strong>}
        </span>
        <div className="ed-acciones">
          <button type="button" className="btn btn-contorno" onClick={() => void guardar()} disabled={guardando || publicando}>
            {guardando ? t.editor.guardando : t.editor.guardarBorrador}
          </button>
          <button type="button" className="btn btn-primario" onClick={() => void publicarVersion(false)} disabled={guardando || publicando}>
            {publicando ? t.editor.publicando : t.editor.publicar(siguiente)}
          </button>
        </div>
      </header>

      {borrador.desdeVersion && <p className="alerta-info">{t.editor.inicioDesdeVersion}</p>}
      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}
      {conflicto && (
        <p className="alerta-error" role="alert">
          {t.editor.conflicto}{" "}
          <button type="button" className="btn-enlace" onClick={recargar}>
            {t.editor.recargar}
          </button>
        </p>
      )}

      <div className="ed-disposicion">
        <EditorVisual contenido={borrador.contenido} variables={variables} alCambiar={marcarSucio} alCrear={alCrear} />
        <aside className="ed-lateral" aria-label={t.vistaPrevia.titulo}>
          <VistaPrevia plantillaId={id} guardarAntes={async () => (sucio ? guardar() : true)} />
          <PanelValidacion resultado={validacion} validando={validando} error={errorValidacion} alValidar={() => void validar()} />
          <ListaVersiones versiones={versiones.data ?? []} restaurando={restaurando} alRestaurar={(n) => void restaurar(n)} />
        </aside>
      </div>

      {sensiblesAConfirmar && (
        <Dialogo
          titulo={t.sensibles.titulo}
          alCerrar={() => setSensiblesAConfirmar(null)}
          acciones={
            <>
              <button type="button" className="btn btn-contorno" onClick={() => setSensiblesAConfirmar(null)}>
                {t.sensibles.cancelar}
              </button>
              <button type="button" className="btn btn-primario" onClick={() => void publicarVersion(true)} disabled={publicando}>
                {t.sensibles.confirmar}
              </button>
            </>
          }
        >
          <p>{t.sensibles.texto}</p>
          <ul className="ed-sensibles">
            {sensiblesAConfirmar.map((v) => (
              <li key={v}>{`{{${v}}}`}</li>
            ))}
          </ul>
        </Dialogo>
      )}
    </div>
  );
}
