import { useId } from "react";
import { BurbujaMensaje } from "../comun";
import type { CampoDto, PlantillaMensaje } from "../api";
import { esNombrada, nombresDeVariables } from "../formato";
import { t } from "../textos";

export interface VariableUI {
  origen: "COLABORADOR" | "FIJO";
  campo: string;
  valor: string;
}
export const variableVacia = (): VariableUI => ({ origen: "COLABORADOR", campo: "", valor: "" });

interface Props {
  plantillas: PlantillaMensaje[];
  plantillaId: string;
  alElegirPlantilla: (id: string) => void;
  variables: Record<string, VariableUI>;
  alCambiarVariable: (n: string, v: VariableUI) => void;
  camposDinamicos: CampoDto[];
  errores: Record<string, string>;
}

/** Texto de la plantilla con las variables fijas ya sustituidas (como `vista_previa` de la API). */
export function vistaPrevia(texto: string, variables: Record<string, VariableUI>, etiquetaCampo: (c: string) => string): string {
  return texto.replace(/\{\{([^{}]+)\}\}/g, (_m, n: string) => {
    const v = variables[n];
    if (!v) return `{{${n}}}`;
    if (v.origen === "FIJO") return v.valor.trim() || `{{${n}}}`;
    return v.campo ? `{{${etiquetaCampo(v.campo)}}}` : `{{${n}}}`;
  });
}

/** Plantilla aprobada + variables. No existe texto libre (CC-REQ-104). */
export function Mensaje({ plantillas, plantillaId, alElegirPlantilla, variables, alCambiarVariable, camposDinamicos, errores }: Props) {
  const idPlantilla = useId();
  const plantilla = plantillas.find((p) => String(p.id) === plantillaId);
  const numeros = plantilla ? nombresDeVariables(plantilla) : [];
  const nombrada = plantilla ? esNombrada(plantilla) : false;
  const etiquetaCampo = (c: string) => t.variablesFijas[c] ?? camposDinamicos.find((d) => d.codigo_interno === c)?.nombre_campo ?? c;

  return (
    <section className="tarjeta not-seccion" aria-labelledby="not-mensaje">
      <h2 id="not-mensaje">{t.nueva.mensaje}</h2>
      <p className="not-etiqueta-seccion">{t.nueva.canal}</p>
      <p className="not-canal">
        <span className="not-radio-fijo" aria-hidden="true" /> {t.nueva.canalPlantilla}
        <span className="not-suave">{` · ${t.nueva.canalAyuda}`}</span>
      </p>

      <div className="campo">
        <label htmlFor={idPlantilla}>{t.nueva.plantilla}</label>
        <select
          id={idPlantilla}
          value={plantillaId}
          aria-invalid={errores.plantilla_mensaje_id ? true : undefined}
          onChange={(e) => alElegirPlantilla(e.target.value)}
        >
          <option value="">{t.nueva.plantillaElige}</option>
          {plantillas.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {`${p.nombre} · ${t.plantillas.estados[p.estado_meta]?.toUpperCase() ?? p.estado_meta}`}
            </option>
          ))}
        </select>
        {plantillas.length === 0 && <span className="ayuda">{t.nueva.sinPlantillas}</span>}
        {errores.plantilla_mensaje_id && (
          <span className="error" role="alert">
            {errores.plantilla_mensaje_id}
          </span>
        )}
      </div>

      {numeros.length > 0 && (
        <>
          <p className="not-etiqueta-seccion">{nombrada ? t.nueva.variablesConNombre : t.nueva.variables}</p>
          {numeros.map((n) => {
            const v = variables[n] ?? variableVacia();
            const error = errores[`variables.${n}`];
            return (
              <div key={n} className={nombrada ? "not-variable not-variable-nombrada" : "not-variable"}>
                {nombrada && (
                  <code className="not-variable-nombre" title={t.nueva.variableConNombre}>
                    {n}
                  </code>
                )}
                <select
                  aria-label={t.nueva.variableOrigen(n)}
                  value={v.origen}
                  onChange={(e) => alCambiarVariable(n, { ...v, origen: e.target.value as VariableUI["origen"] })}
                >
                  <option value="COLABORADOR">{t.nueva.origenColaborador}</option>
                  <option value="FIJO">{t.nueva.origenFijo}</option>
                </select>
                {v.origen === "COLABORADOR" ? (
                  <select
                    aria-label={t.nueva.variableCampo(n)}
                    value={v.campo}
                    aria-invalid={error ? true : undefined}
                    onChange={(e) => alCambiarVariable(n, { ...v, campo: e.target.value })}
                  >
                    <option value="">{t.nueva.campoElige}</option>
                    {Object.entries(t.variablesFijas).map(([k, etiqueta]) => (
                      <option key={k} value={k}>
                        {etiqueta}
                      </option>
                    ))}
                    {camposDinamicos.map((d) => (
                      <option key={d.codigo_interno} value={d.codigo_interno}>
                        {d.nombre_campo}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label={t.nueva.variableValor(n)}
                    value={v.valor}
                    maxLength={200}
                    aria-invalid={error ? true : undefined}
                    onChange={(e) => alCambiarVariable(n, { ...v, valor: e.target.value })}
                  />
                )}
                {error && (
                  <span className="error not-error" role="alert">
                    {error}
                  </span>
                )}
              </div>
            );
          })}
        </>
      )}

      {plantilla && (
        <>
          <p className="not-etiqueta-seccion">{t.nueva.vistaPrevia}</p>
          <BurbujaMensaje texto={vistaPrevia(plantilla.texto_con_variables, variables, etiquetaCampo)} />
        </>
      )}
    </section>
  );
}
