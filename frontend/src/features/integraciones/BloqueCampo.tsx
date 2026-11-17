import { useId, type ReactNode } from "react";
import { t } from "./textos";

export interface Ayuda {
  resumen: string;
  pasos: string[];
}

interface PropsControl {
  id: string;
  describedBy: string;
  invalido: boolean;
}

interface Props {
  etiqueta: string;
  ayuda: Ayuda;
  error?: string;
  /** Si es falso no hay control que etiquetar (p. ej. un secreto ya configurado): la etiqueta es solo texto. */
  conControl?: boolean;
  children: (p: PropsControl) => ReactNode;
}

/**
 * Campo con su ayuda siempre visible junto a él: el resumen está a la vista y, en un desplegable,
 * los pasos para encontrar el dato en el panel de Meta (CC-NFR-012: nada de ayuda escondida en
 * un tooltip).
 */
export function BloqueCampo({ etiqueta, ayuda, error, conControl = true, children }: Props) {
  const id = useId();
  const idAyuda = `${id}-ayuda`;
  const idError = `${id}-error`;
  const describedBy = error ? `${idAyuda} ${idError}` : idAyuda;
  return (
    <div className="campo int-campo">
      {conControl ? <label htmlFor={id}>{etiqueta}</label> : <span className="int-etiqueta">{etiqueta}</span>}
      {children({ id, describedBy, invalido: Boolean(error) })}
      {error && (
        <span id={idError} className="error" role="alert">
          {error}
        </span>
      )}
      <div id={idAyuda} className="int-ayuda">
        <p>{ayuda.resumen}</p>
        {ayuda.pasos.length > 0 && (
          <details>
            <summary>{t.ayudas.verPasos}</summary>
            <ul>
              {ayuda.pasos.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
