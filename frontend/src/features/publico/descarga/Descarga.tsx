import { useEffect, useState } from "react";
import { revisarEnlace, rutaDescarga, type EstadoEnlace } from "../api";
import { t } from "../textos";
import { usePaginaPrivada } from "../usoPrivado";
import "../publico.css";

/**
 * Descarga por enlace de un solo uso (CON-20 y CON-21). Revisa el enlace con un GET que no lo
 * consume; la descarga es un formulario POST nativo (el navegador sigue el 302 al PDF firmado).
 * El token no se guarda en almacenamiento ni se escribe en logs.
 */
export function Descarga({ token }: { token: string }) {
  usePaginaPrivada(t.descarga.titulo);
  const [estado, setEstado] = useState<EstadoEnlace | null>(null);

  useEffect(() => {
    const control = new AbortController();
    setEstado(null);
    void revisarEnlace(token, control.signal).then((e) => {
      if (!control.signal.aborted) setEstado(e);
    });
    return () => control.abort();
  }, [token]);

  return (
    <main className="pub">
      <div className="pub-tarjeta">
        <div className="pub-marca">{t.marca}</div>
        {estado === null && <p role="status">{t.cargando}</p>}
        {estado === "VIGENTE" && (
          <>
            <h1>{t.descarga.titulo}</h1>
            <p>{t.descarga.ayuda}</p>
            <form method="post" action={rutaDescarga(token)}>
              <button type="submit" className="btn btn-primario pub-boton">
                {t.descarga.boton}
              </button>
            </form>
          </>
        )}
        {estado === "NO_VIGENTE" && (
          <div role="alert">
            <h1>{t.descarga.invalidoTitulo}</h1>
            <p className="pub-aviso">{t.descarga.invalido}</p>
          </div>
        )}
        {estado === "ERROR" && (
          <p className="pub-aviso" role="alert">
            {t.descarga.error}
          </p>
        )}
      </div>
    </main>
  );
}
