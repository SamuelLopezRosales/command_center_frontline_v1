import { useQuery } from "@tanstack/react-query";
import { ErrorApi } from "@/shared/errores";
import { fechaCorta } from "@/shared/fechas";
import { verificar } from "../api";
import { t } from "../textos";
import { usePaginaPrivada } from "../usoPrivado";
import "../publico.css";

/** Verificación pública de una constancia por el código del QR (CON-19). Sin sesión. */
export function Verificacion({ codigo }: { codigo: string }) {
  usePaginaPrivada(t.verificacion.titulo);
  const r = useQuery({
    queryKey: ["publico", "verificar", codigo],
    queryFn: () => verificar(codigo),
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });

  const noExiste = r.error instanceof ErrorApi && r.error.status === 404;

  return (
    <main className="pub">
      <div className="pub-tarjeta">
        <div className="pub-marca">{t.marca}</div>
        <h1>{t.verificacion.titulo}</h1>
        {r.isPending && <p role="status">{t.cargando}</p>}
        {noExiste && (
          <div role="alert">
            <p className="pub-aviso">{t.verificacion.noEncontrada}</p>
            <p className="pub-suave">{t.verificacion.noEncontradaAyuda}</p>
          </div>
        )}
        {r.isError && !noExiste && (
          <p className="pub-aviso" role="alert">
            {t.verificacion.error}
          </p>
        )}
        {r.data && (
          <dl className="pub-datos">
            <dt>{t.verificacion.nombre}</dt>
            <dd>{r.data.nombre}</dd>
            <dt>{t.verificacion.folio}</dt>
            <dd>{r.data.folio}</dd>
            <dt>{t.verificacion.fecha}</dt>
            <dd>{fechaCorta(r.data.fecha_emision)}</dd>
            <dt>{t.verificacion.estado}</dt>
            <dd>
              <span className={r.data.estado === "VIGENTE" ? "insignia ok" : "insignia error"}>
                {r.data.estado === "VIGENTE" ? t.verificacion.vigente : r.data.estado === "CANCELADA" ? t.verificacion.cancelada : r.data.estado}
              </span>
            </dd>
          </dl>
        )}
      </div>
    </main>
  );
}
