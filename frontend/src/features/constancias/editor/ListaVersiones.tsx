import type { Version } from "../api";
import { fechaMedia } from "../formato";
import { t } from "../textos";

interface Props {
  versiones: Version[];
  restaurando: number | null;
  alRestaurar: (numero: number) => void;
}

/** Versiones publicadas; restaurar crea una versión nueva y no cambia la original. */
export function ListaVersiones({ versiones, restaurando, alRestaurar }: Props) {
  const orden = [...versiones].sort((a, b) => b.numero - a.numero);
  return (
    <section className="ed-seccion" aria-labelledby="ed-ver-titulo">
      <h2 id="ed-ver-titulo">{t.versiones.titulo}</h2>
      {orden.length === 0 ? (
        <p className="ed-suave">{t.versiones.vacio}</p>
      ) : (
        <ul className="ed-versiones">
          {orden.map((v) => (
            <li key={v.numero} className="ed-version">
              <span>{t.versiones.etiqueta(v.numero, fechaMedia(v.fecha_creacion))}</span>
              {v.vigente ? (
                <span className="insignia ok">{t.versiones.activa}</span>
              ) : (
                <button
                  type="button"
                  className="btn-enlace"
                  aria-label={`${t.versiones.restaurar} v${v.numero}`}
                  disabled={restaurando !== null}
                  onClick={() => alRestaurar(v.numero)}
                >
                  {restaurando === v.numero ? t.versiones.restaurando : t.versiones.restaurar}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
