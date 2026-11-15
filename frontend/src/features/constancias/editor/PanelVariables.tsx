import { useMemo, useState } from "react";
import type { Variable } from "../api";
import { t } from "../textos";

const ORDEN = ["COLABORADOR", "ORGANIZACION", "SENSIBLES", "SISTEMA"] as const;

interface Props {
  variables: Variable[];
  alInsertar: (v: Variable) => void;
}

/** Panel izquierdo del editor: variables agrupadas, con buscador (cv1_06). */
export function PanelVariables({ variables, alInsertar }: Props) {
  const [q, setQ] = useState("");

  const grupos = useMemo(() => {
    const filtro = q.trim().toLowerCase();
    const visibles = variables.filter(
      (v) => !filtro || v.nombre.toLowerCase().includes(filtro) || v.etiqueta.toLowerCase().includes(filtro),
    );
    return ORDEN.map((g) => ({ grupo: g, items: visibles.filter((v) => v.grupo === g) })).filter((g) => g.items.length > 0);
  }, [variables, q]);

  return (
    <section className="ed-variables" aria-label={t.variables.titulo}>
      <h2>{t.variables.titulo}</h2>
      <input
        type="search"
        className="ed-buscador"
        aria-label={t.variables.buscar}
        placeholder={t.variables.buscar}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {grupos.length === 0 && <p className="ed-suave">{t.variables.sinResultados}</p>}
      {grupos.map(({ grupo, items }) => (
        <div key={grupo} role="group" aria-labelledby={`ed-grupo-${grupo}`}>
          <h3 id={`ed-grupo-${grupo}`} className="ed-grupo">
            {t.variables.grupos[grupo]}
          </h3>
          <ul className="ed-lista-variables">
            {items.map((v) => {
              const sensible = v.sensible || v.grupo === "SENSIBLES";
              return (
                <li key={v.nombre}>
                  <button
                    type="button"
                    className={sensible ? "ed-chip ed-chip-sensible" : "ed-chip"}
                    title={v.etiqueta}
                    aria-label={t.variables.insertar(v.nombre)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => alInsertar(v)}
                  >
                    {`{{${v.nombre}}}`}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}
