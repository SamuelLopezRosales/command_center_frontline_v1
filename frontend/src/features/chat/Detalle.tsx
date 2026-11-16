import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ErrorApi, mensajeDeError } from "@/shared/errores";
import { fechaHora } from "@/shared/fechas";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { asignarConversacion, listarMensajes, listarUsuariosAsignables, type Conversacion, type Mensaje } from "./api";
import { Redactor } from "./Redactor";
import { t } from "./textos";
import { IndicadorVentana, useAhora, ventanaAbierta } from "./Ventana";

function Burbuja({ m }: { m: Mensaje }) {
  const entrante = m.direccion === "ENTRANTE";
  const cuerpo =
    m.contenido ?? (m.tipo === "PLANTILLA" && m.plantilla ? t.detalle.plantillaEtiqueta(m.plantilla) : m.tipo === "INTERACTIVO" ? t.detalle.interactivo : t.detalle.sinContenido);
  return (
    <li className={`chat-burbuja ${entrante ? "chat-entrante" : "chat-saliente"}`}>
      <span className="chat-autor">{entrante ? t.detalle.entrante : t.detalle.saliente}</span>
      <p>{cuerpo}</p>
      <span className="chat-meta">
        {fechaHora(m.fecha_hora)}
        {!entrante && ` · ${t.detalle.estados[m.estado] ?? m.estado}`}
      </span>
    </li>
  );
}

function Asignacion({ conversacion }: { conversacion: Conversacion }) {
  const { tiene, usuario } = useSesion();
  const cliente = useQueryClient();
  const puedeListar = tiene("usuarios:administrar");
  const usuarios = useQuery({ queryKey: ["chat", "usuarios"], queryFn: listarUsuariosAsignables, enabled: puedeListar });
  const [elegido, setElegido] = useState("");
  const [aviso, setAviso] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  async function asignar(usuarioId: number) {
    setOcupado(true);
    setAviso(null);
    try {
      await asignarConversacion(conversacion.id, usuarioId);
      setAviso({ tipo: "ok", texto: t.asignacion.asignada });
      void cliente.invalidateQueries({ queryKey: ["chat", "conversaciones"] });
    } catch (e) {
      // 422: el usuario no existe o es de otra empresa.
      setAviso({ tipo: "error", texto: e instanceof ErrorApi && e.status === 422 ? t.asignacion.errorUsuario : mensajeDeError(e) });
    } finally {
      setOcupado(false);
    }
  }

  return (
    <section className="chat-asignacion" aria-label={t.asignacion.titulo}>
      {aviso && (
        <p className={aviso.tipo === "ok" ? "alerta-info" : "alerta-error"} role={aviso.tipo === "ok" ? "status" : "alert"}>
          {aviso.texto}
        </p>
      )}
      <div className="chat-asignacion-fila">
        {puedeListar && (
          <>
            <label htmlFor="chat-asignar-a">{t.asignacion.usuario}</label>
            <select id="chat-asignar-a" value={elegido} onChange={(e) => setElegido(e.target.value)}>
              <option value="">{t.asignacion.elegir}</option>
              {usuarios.data
                ?.filter((u) => u.activo)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.nombre}
                  </option>
                ))}
            </select>
            <button type="button" className="btn btn-contorno" disabled={!elegido || ocupado} onClick={() => void asignar(Number(elegido))}>
              {t.asignacion.asignar}
            </button>
          </>
        )}
        {usuario && (
          <button type="button" className="btn btn-contorno" disabled={ocupado} onClick={() => void asignar(usuario.id)}>
            {t.asignacion.asignarme}
          </button>
        )}
      </div>
    </section>
  );
}

/** Detalle de la conversación (WAP-02) con el redactor y la asignación. Se monta con `key` por conversación. */
export function Detalle({ conversacion }: { conversacion: Conversacion }) {
  const ahora = useAhora();
  const [cerradaPorServidor, setCerradaPorServidor] = useState(false);
  const abierta = !cerradaPorServidor && ventanaAbierta(conversacion.ventana_abierta, conversacion.ultimo_mensaje_entrante_at, ahora);

  const mensajes = useInfiniteQuery({
    queryKey: ["chat", "mensajes", conversacion.id],
    queryFn: ({ pageParam }) => listarMensajes(conversacion.id, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (ultima) => ultima.siguiente ?? undefined,
  });

  // La API entrega del más reciente al más antiguo; en pantalla el hilo se lee de arriba abajo.
  const hilo = useMemo(() => (mensajes.data?.pages.flatMap((p) => p.items) ?? []).slice().reverse(), [mensajes.data]);

  return (
    <div className="chat-detalle">
      <header className="chat-detalle-cabecera">
        <div>
          <h2>{conversacion.colaborador_nombre ?? t.lista.sinNombre}</h2>
          <span className="chat-suave">{t.lista.origenes[conversacion.origen]}</span>
        </div>
        <IndicadorVentana abierta={abierta} ultimoEntrante={conversacion.ultimo_mensaje_entrante_at} ahora={ahora} />
      </header>

      <Asignacion conversacion={conversacion} />

      {mensajes.isPending && <p role="status">{t.cargando}</p>}
      {mensajes.isError && (
        <p className="alerta-error" role="alert">
          {t.detalle.errorMensajes}
        </p>
      )}
      {mensajes.data && (
        <>
          {mensajes.hasNextPage && (
            <button type="button" className="btn btn-contorno chat-anteriores" disabled={mensajes.isFetchingNextPage} onClick={() => void mensajes.fetchNextPage()}>
              {t.detalle.anteriores}
            </button>
          )}
          {hilo.length === 0 ? (
            <p className="chat-vacio">{t.detalle.sinMensajes}</p>
          ) : (
            <ul className="chat-hilo" aria-label={t.detalle.mensajesAria}>
              {hilo.map((m) => (
                <Burbuja key={m.id} m={m} />
              ))}
            </ul>
          )}
        </>
      )}

      <Redactor conversacionId={conversacion.id} ventanaAbierta={abierta} forzadaPorServidor={cerradaPorServidor} alCerrarseVentana={() => setCerradaPorServidor(true)} />
    </div>
  );
}
