import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fechaHora } from "@/shared/fechas";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { CLAVE_ESTADO, leerEstadoMeta, type EstadoMeta } from "./api";
import { FormularioMeta } from "./FormularioMeta";
import { ProbarConexion } from "./ProbarConexion";
import { UrlWebhook } from "./UrlWebhook";
import { t } from "./textos";
import "./integraciones.css";

/** Qué datos faltan, en el orden de la guía. */
export function datosFaltantes(e: EstadoMeta): string[] {
  const falta: string[] = [];
  if (!e.waba_id) falta.push(t.campos.waba_id);
  if (!e.phone_number_id) falta.push(t.campos.phone_number_id);
  if (!e.access_token.configurado) falta.push(t.campos.access_token);
  if (!e.app_secret.configurado) falta.push(t.campos.app_secret);
  if (!e.verify_token.configurado) falta.push(t.campos.verify_token);
  return falta;
}

function Estado({ e }: { e: EstadoMeta }) {
  const falta = datosFaltantes(e);
  return (
    <section className="tarjeta int-seccion" aria-labelledby="int-estado-titulo">
      <h2 id="int-estado-titulo">{t.estado.titulo}</h2>
      <p>
        <span className={`insignia ${e.configurada ? "ok" : "proceso"}`}>{e.configurada ? t.estado.configurada : t.estado.faltan}</span>
      </p>
      <p>{falta.length > 0 ? t.estado.faltanLista(falta) : t.estado.todoCapturado}</p>
      <p className="int-suave">{e.actualizado_en ? t.estado.actualizado(fechaHora(e.actualizado_en)) : t.estado.sinActualizacion}</p>
    </section>
  );
}

/** Conexión con Meta (WhatsApp Cloud API): captura de credenciales, URL del webhook y prueba. */
export function PaginaMeta() {
  const { estado: sesion, tiene } = useSesion();
  const cliente = useQueryClient();
  const puede = tiene("integraciones:administrar");
  const consulta = useQuery({ queryKey: CLAVE_ESTADO, queryFn: leerEstadoMeta, enabled: puede });

  if (sesion === "cargando") return <p role="status">{t.cargando}</p>;
  if (!puede)
    return (
      <div className="int">
        <h1>{t.titulo}</h1>
        <p className="alerta-error" role="alert">
          {t.sinPermiso}
        </p>
      </div>
    );

  return (
    <div className="int">
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
      </div>
      <p className="alerta-info int-pendiente" role="note">
        {t.pendienteDeDiseno}
      </p>

      {consulta.isPending && <p role="status">{t.cargando}</p>}
      {consulta.isError && (
        <p className="alerta-error" role="alert">
          {t.errorCarga}{" "}
          <button type="button" className="btn-enlace" onClick={() => void consulta.refetch()}>
            {t.reintentar}
          </button>
        </p>
      )}
      {consulta.data && (
        <>
          <Estado e={consulta.data} />
          <FormularioMeta
            estado={consulta.data}
            alGuardar={(nuevo) => cliente.setQueryData(CLAVE_ESTADO, nuevo)}
            alGenerarToken={() => void cliente.invalidateQueries({ queryKey: CLAVE_ESTADO })}
          />
          <UrlWebhook />
          <ProbarConexion />
        </>
      )}
    </div>
  );
}
