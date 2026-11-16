import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { buscarColaboradores, type Audiencia as AudienciaGuardada } from "../api";
import { t } from "../textos";
import { ConstructorCriterios } from "./ConstructorCriterios";
import type { Catalogo, Grupo } from "./criterios";

export type Modo = "CRITERIOS" | "INDIVIDUAL" | "GRUPO";
export interface ColaboradorElegido {
  id: number;
  nombre: string | null;
}

interface Props {
  modo: Modo;
  alCambiarModo: (m: Modo) => void;
  raiz: Grupo;
  alCambiarRaiz: (g: Grupo) => void;
  catalogo: Catalogo;
  erroresCriterios: Map<string, string>;
  grupos: AudienciaGuardada[];
  audienciaId: string;
  alCambiarAudiencia: (id: string) => void;
  colaborador: ColaboradorElegido | null;
  alElegirColaborador: (c: ColaboradorElegido) => void;
  errorAudiencia?: string;
  errorColaborador?: string;
}

function Individual({ colaborador, alElegir, error }: { colaborador: ColaboradorElegido | null; alElegir: (c: ColaboradorElegido) => void; error?: string }) {
  const id = useId();
  const [q, setQ] = useState("");
  const termino = q.trim();
  const resultados = useQuery({
    queryKey: ["notificaciones", "colaboradores", termino],
    queryFn: () => buscarColaboradores(termino),
    enabled: termino.length >= 2,
  });
  return (
    <div>
      <div className="campo">
        <label htmlFor={id}>{t.nueva.individualBuscar}</label>
        <input id={id} type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-invalid={error ? true : undefined} />
      </div>
      {resultados.data &&
        (resultados.data.items.length === 0 ? (
          <p className="not-suave">{t.nueva.individualSinResultados}</p>
        ) : (
          <ul className="not-resultados">
            {resultados.data.items.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  className="btn-enlace"
                  aria-label={t.nueva.individualElegir(c.nombre_completo)}
                  onClick={() => {
                    alElegir({ id: c.id, nombre: c.nombre_completo });
                    setQ("");
                  }}
                >
                  {c.nombre_completo}
                </button>
                <span className="not-suave">{` · ${c.numero_empleado} · ${c.planta.nombre}`}</span>
              </li>
            ))}
          </ul>
        ))}
      {colaborador && (
        <p className="alerta-info" role="status">
          {colaborador.nombre ? t.nueva.individualSeleccionado(colaborador.nombre) : t.nueva.individualSeleccionadoId(colaborador.id)}
        </p>
      )}
      {error && (
        <span className="error not-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/** «¿A quién le escribimos?»: criterios, colaborador individual o grupo guardado. */
export function Audiencia(p: Props) {
  const idGrupo = useId();
  return (
    <section className="tarjeta not-seccion" aria-labelledby="not-aquien">
      <h2 id="not-aquien">{t.nueva.aQuien}</h2>
      <div role="radiogroup" aria-label={t.nueva.modosAria} className="not-modos">
        {(Object.keys(t.nueva.modos) as Modo[]).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={p.modo === m}
            className={p.modo === m ? "activa" : undefined}
            onClick={() => p.alCambiarModo(m)}
          >
            {t.nueva.modos[m]}
          </button>
        ))}
      </div>

      {p.modo === "CRITERIOS" && (
        <ConstructorCriterios raiz={p.raiz} catalogo={p.catalogo} alCambiar={p.alCambiarRaiz} errores={p.erroresCriterios} />
      )}
      {p.modo === "INDIVIDUAL" && <Individual colaborador={p.colaborador} alElegir={p.alElegirColaborador} error={p.errorColaborador} />}
      {p.modo === "GRUPO" && (
        <div className="campo">
          <label htmlFor={idGrupo}>{t.nueva.grupoEtiqueta}</label>
          <select
            id={idGrupo}
            value={p.audienciaId}
            aria-invalid={p.errorAudiencia ? true : undefined}
            onChange={(e) => p.alCambiarAudiencia(e.target.value)}
          >
            <option value="">{t.nueva.grupoElige}</option>
            {p.grupos.map((g) => (
              <option key={g.id} value={String(g.id)}>
                {g.nombre}
              </option>
            ))}
          </select>
          {p.grupos.length === 0 && <span className="ayuda">{t.nueva.sinGrupos}</span>}
          {p.errorAudiencia && (
            <span className="error" role="alert">
              {p.errorAudiencia}
            </span>
          )}
        </div>
      )}
    </section>
  );
}
