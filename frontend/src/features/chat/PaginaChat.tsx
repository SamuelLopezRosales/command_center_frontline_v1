import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fechaHora } from "@/shared/fechas";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { listarConversaciones, listarUsuariosAsignables, type Conversacion, type EstadoConversacion, type FiltroConversaciones } from "./api";
import { Detalle } from "./Detalle";
import { t } from "./textos";
import { IndicadorVentana, useAhora, ventanaAbierta } from "./Ventana";
import "./chat.css";

const LIMITE = 20;
const ESTADOS: EstadoConversacion[] = ["ACTIVA", "VERIFICANDO", "BLOQUEADA", "CERRADA"];

/** Chat de RH (WAP-01 a 05): conversaciones a la izquierda, hilo y respuesta a la derecha. */
export function PaginaChat() {
  const { estado: estadoSesion, tiene, usuario } = useSesion();
  const [params, setParams] = useSearchParams();
  const [estado, setEstado] = useState<"" | EstadoConversacion>("");
  const [soloMias, setSoloMias] = useState(false);
  const [cursores, setCursores] = useState<(string | undefined)[]>([undefined]);
  const [seleccionada, setSeleccionada] = useState<Conversacion | null>(null);
  const ahora = useAhora();

  // Los enlaces desde una notificación llegan con `?notificacion=`.
  const notificacion = Number(params.get("notificacion")) || undefined;

  const filtro: FiltroConversaciones = {
    notificacion_id: notificacion,
    asignada_a: soloMias ? usuario?.id : undefined,
    estado: estado || undefined,
    cursor: cursores.at(-1),
    limite: LIMITE,
  };

  const puedeUsar = tiene("chat:responder");
  const lista = useQuery({
    queryKey: ["chat", "conversaciones", filtro],
    queryFn: () => listarConversaciones(filtro),
    placeholderData: (previo) => previo,
    enabled: puedeUsar,
  });
  const usuarios = useQuery({ queryKey: ["chat", "usuarios"], queryFn: listarUsuariosAsignables, enabled: puedeUsar && tiene("usuarios:administrar") });

  if (estadoSesion === "cargando") return <p role="status">{t.cargando}</p>;
  if (!puedeUsar)
    return (
      <div className="chat">
        <h1>{t.titulo}</h1>
        <p className="alerta-error" role="alert">
          {t.sinPermiso}
        </p>
      </div>
    );

  const cambiar = (fn: () => void) => {
    fn();
    setCursores([undefined]);
  };
  const datos = lista.data;
  // La conversación abierta se refresca con la lista (ventana, asignación); si ya no sale, se conserva la última lectura.
  const actual = seleccionada ? (datos?.items.find((c) => c.id === seleccionada.id) ?? seleccionada) : null;

  function nombreDeAsignado(id: number): string {
    if (id === usuario?.id) return t.lista.tu;
    return usuarios.data?.find((u) => u.id === id)?.nombre ?? t.lista.usuarioNumero(id);
  }

  return (
    <div className="chat">
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
      </div>
      <p className="alerta-info chat-pendiente" role="note">
        {t.pendienteDeDiseno}
      </p>

      <div className="chat-disposicion">
        <section className="chat-panel-lista" aria-label={t.lista.aria}>
          <form className="chat-filtros" role="search" aria-label={t.lista.filtros} onSubmit={(e) => e.preventDefault()}>
            <select aria-label={t.lista.estado} value={estado} onChange={(e) => cambiar(() => setEstado(e.target.value as "" | EstadoConversacion))}>
              <option value="">{t.lista.todosEstados}</option>
              {ESTADOS.map((s) => (
                <option key={s} value={s}>
                  {t.lista.estados[s]}
                </option>
              ))}
            </select>
            <label className="chat-casilla">
              <input type="checkbox" checked={soloMias} onChange={(e) => cambiar(() => setSoloMias(e.target.checked))} />
              {t.lista.mias}
            </label>
            <input
              type="number"
              min={1}
              aria-label={t.lista.notificacion}
              placeholder={t.lista.notificacion}
              value={notificacion ?? ""}
              onChange={(e) => {
                const siguiente = new URLSearchParams(params);
                if (e.target.value) siguiente.set("notificacion", e.target.value);
                else siguiente.delete("notificacion");
                setParams(siguiente, { replace: true });
                setCursores([undefined]);
              }}
            />
          </form>

          {lista.isPending && <p role="status">{t.cargando}</p>}
          {lista.isError && (
            <p className="alerta-error" role="alert">
              {t.errorCarga}{" "}
              <button type="button" className="btn-enlace" onClick={() => void lista.refetch()}>
                {t.reintentar}
              </button>
            </p>
          )}
          {datos &&
            (datos.items.length === 0 ? (
              <p className="chat-vacio">{t.lista.vacia}</p>
            ) : (
              <ul className="chat-conversaciones">
                {datos.items.map((c) => {
                  const abierta = ventanaAbierta(c.ventana_abierta, c.ultimo_mensaje_entrante_at, ahora);
                  return (
                    <li key={c.id}>
                      <button type="button" className={`chat-conversacion ${actual?.id === c.id ? "activa" : ""}`} aria-current={actual?.id === c.id ? "true" : undefined} onClick={() => setSeleccionada(c)}>
                        <span className="chat-conv-nombre">{c.colaborador_nombre ?? t.lista.sinNombre}</span>
                        <span className="chat-conv-fila">
                          <IndicadorVentana abierta={abierta} ultimoEntrante={c.ultimo_mensaje_entrante_at} ahora={ahora} />
                        </span>
                        <span className="chat-conv-fila chat-suave">
                          <span>{t.lista.estados[c.estado] ?? c.estado}</span>
                          <span>{t.lista.origenes[c.origen] ?? c.origen}</span>
                          <span>{fechaHora(c.fecha_ultimo_mensaje)}</span>
                        </span>
                        <span className="chat-conv-asignacion">
                          {c.asignada_a_usuario_id ? t.lista.asignadaA(nombreDeAsignado(c.asignada_a_usuario_id)) : t.lista.sinAsignar}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ))}
          {datos && (
            <div className="chat-pie">
              <button type="button" className="btn btn-contorno" disabled={cursores.length <= 1} onClick={() => setCursores((c) => c.slice(0, -1))}>
                {t.lista.anterior}
              </button>
              <button type="button" className="btn btn-contorno" disabled={!datos.siguiente} onClick={() => setCursores((c) => [...c, datos.siguiente ?? undefined])}>
                {t.lista.siguiente}
              </button>
            </div>
          )}
        </section>

        <section className="chat-panel-detalle">
          {actual ? <Detalle key={actual.id} conversacion={actual} /> : <p className="chat-vacio">{t.detalle.elegir}</p>}
        </section>
      </div>
    </div>
  );
}
