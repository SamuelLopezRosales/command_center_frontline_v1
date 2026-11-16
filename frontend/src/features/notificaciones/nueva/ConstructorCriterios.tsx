import { t } from "../textos";
import {
  contarHojas,
  esGrupo,
  grupoNuevo,
  hojaVacia,
  MAX_CRITERIOS,
  operadoresDe,
  usaOpciones,
  type Catalogo,
  type DefCriterio,
  type Grupo,
  type Hoja,
  type Nodo,
} from "./criterios";

interface Props {
  raiz: Grupo;
  catalogo: Catalogo;
  alCambiar: (nueva: Grupo) => void;
  /** Mensaje por clave de nodo (errores locales y del servidor ya combinados). */
  errores: Map<string, string>;
}

/** Aplica `fn` al nodo con esa clave y devuelve el árbol nuevo (inmutable). */
function transformar(g: Grupo, clave: string, fn: (n: Nodo) => Nodo | null): Grupo {
  if (g.clave === clave) return (fn(g) ?? g) as Grupo;
  return {
    ...g,
    items: g.items.flatMap((i) => {
      if (i.clave === clave) {
        const r = fn(i);
        return r ? [r] : [];
      }
      return [esGrupo(i) ? transformar(i, clave, fn) : i];
    }),
  };
}

function numerar(g: Grupo, m = new Map<string, number>()): Map<string, number> {
  for (const i of g.items) {
    if (esGrupo(i)) numerar(i, m);
    else m.set(i.clave, m.size + 1);
  }
  return m;
}

function Valor({ def, hoja, n, cambiar }: { def: DefCriterio; hoja: Hoja; n: number; cambiar: (c: Partial<Hoja>) => void }) {
  const etiqueta = `${t.criterios.valor} ${n}`;
  const hasta = `${t.criterios.valorHasta} ${n}`;
  if (def.tipo === "SI_NO") {
    return (
      <select aria-label={etiqueta} value={hoja.v1} onChange={(e) => cambiar({ v1: e.target.value })}>
        <option value="">{t.criterios.elige}</option>
        <option value="true">{t.criterios.si}</option>
        <option value="false">{t.criterios.no}</option>
      </select>
    );
  }
  if (usaOpciones(def.tipo)) {
    const opciones = def.opciones ?? [];
    if (hoja.operador === "en") {
      return (
        <select
          multiple
          aria-label={etiqueta}
          value={hoja.lista}
          onChange={(e) => cambiar({ lista: Array.from(e.target.selectedOptions, (o) => o.value) })}
        >
          {opciones.map((o) => (
            <option key={o.valor} value={o.valor}>
              {o.etiqueta}
            </option>
          ))}
        </select>
      );
    }
    return (
      <select aria-label={etiqueta} value={hoja.v1} onChange={(e) => cambiar({ v1: e.target.value })}>
        <option value="">{t.criterios.elige}</option>
        {opciones.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.etiqueta}
          </option>
        ))}
      </select>
    );
  }
  const tipoInput = def.tipo === "FECHA" ? "date" : def.tipo === "TEXTO" ? "text" : "number";
  const sufijo = def.tipo === "ANTIGUEDAD" ? <span className="not-sufijo">{t.criterios.sufijoAnios}</span> : null;
  return (
    <>
      <input
        type={tipoInput}
        aria-label={etiqueta}
        value={hoja.v1}
        min={def.tipo === "ANTIGUEDAD" ? 0 : undefined}
        onChange={(e) => cambiar({ v1: e.target.value })}
      />
      {hoja.operador === "entre" && (
        <input type={tipoInput} aria-label={hasta} value={hoja.v2} onChange={(e) => cambiar({ v2: e.target.value })} />
      )}
      {sufijo}
    </>
  );
}

function FilaCriterio({
  hoja,
  n,
  catalogo,
  error,
  cambiar,
  quitar,
}: {
  hoja: Hoja;
  n: number;
  catalogo: Catalogo;
  error?: string;
  cambiar: (c: Partial<Hoja>) => void;
  quitar: () => void;
}) {
  const def = catalogo.porCodigo.get(hoja.campo);
  return (
    <div className="not-criterio">
      <div className="not-criterio-fila">
        <select
          aria-label={`${t.criterios.campo} ${n}`}
          value={hoja.campo}
          aria-invalid={error ? true : undefined}
          onChange={(e) => {
            const nuevo = catalogo.porCodigo.get(e.target.value);
            cambiar({ campo: e.target.value, operador: nuevo ? operadoresDe(nuevo.tipo)[0]! : "", v1: "", v2: "", lista: [] });
          }}
        >
          <option value="">{t.criterios.elige}</option>
          {catalogo.lista.map((d) => (
            <option key={d.codigo} value={d.codigo}>
              {d.etiqueta}
            </option>
          ))}
        </select>
        <select
          aria-label={`${t.criterios.operador} ${n}`}
          value={hoja.operador}
          disabled={!def}
          onChange={(e) => cambiar({ operador: e.target.value, lista: [], v2: "" })}
        >
          {def ? (
            operadoresDe(def.tipo).map((o) => (
              <option key={o} value={o}>
                {t.criterios.operadores[o] ?? o}
              </option>
            ))
          ) : (
            <option value="" />
          )}
        </select>
        <div className="not-valor">{def ? <Valor def={def} hoja={hoja} n={n} cambiar={cambiar} /> : <input disabled aria-label={`${t.criterios.valor} ${n}`} />}</div>
        <button type="button" className="btn-enlace not-peligro" aria-label={`${t.criterios.quitar} ${n}`} onClick={quitar}>
          ×
        </button>
      </div>
      {error && (
        <span className="error not-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

function GrupoVista({
  grupo,
  raiz,
  props,
  numeros,
  esRaiz,
}: {
  grupo: Grupo;
  raiz: Grupo;
  props: Props;
  numeros: Map<string, number>;
  esRaiz: boolean;
}) {
  const { catalogo, alCambiar, errores } = props;
  const alcanzado = contarHojas(raiz) >= MAX_CRITERIOS;
  const alternar = () => alCambiar(transformar(raiz, grupo.clave, (g) => ({ ...(g as Grupo), op: (g as Grupo).op === "Y" ? "O" : "Y" })));
  const agregarHoja = () => alCambiar(transformar(raiz, grupo.clave, (g) => ({ ...(g as Grupo), items: [...(g as Grupo).items, hojaVacia()] })));
  const agregarGrupo = () => alCambiar(transformar(raiz, grupo.clave, (g) => ({ ...(g as Grupo), items: [...(g as Grupo).items, grupoNuevo()] })));
  const errorGrupo = errores.get(grupo.clave);

  return (
    <div className={esRaiz ? "not-grupo not-grupo-raiz" : "not-grupo not-subgrupo"} role="group" aria-label={esRaiz ? t.criterios.raizAria : t.criterios.grupoEtiqueta}>
      {grupo.items.map((item, idx) => (
        <div key={item.clave}>
          {idx > 0 && (
            <button type="button" className="not-pildora" aria-label={t.criterios.combinador(grupo.op)} onClick={alternar}>
              {grupo.op}
            </button>
          )}
          {esGrupo(item) ? (
            <div className="not-subgrupo-caja">
              <GrupoVista grupo={item} raiz={raiz} props={props} numeros={numeros} esRaiz={false} />
              <button
                type="button"
                className="btn-enlace not-peligro"
                onClick={() => alCambiar(transformar(raiz, item.clave, () => null))}
              >
                {t.criterios.quitarGrupo}
              </button>
            </div>
          ) : (
            <FilaCriterio
              hoja={item}
              n={numeros.get(item.clave) ?? 0}
              catalogo={catalogo}
              error={errores.get(item.clave)}
              cambiar={(c) => alCambiar(transformar(raiz, item.clave, (h) => ({ ...(h as Hoja), ...c })))}
              quitar={() => alCambiar(transformar(raiz, item.clave, () => null))}
            />
          )}
        </div>
      ))}
      {errorGrupo && (
        <span className="error not-error" role="alert">
          {errorGrupo}
        </span>
      )}
      <div className="not-agregar">
        <button type="button" className="btn-enlace" disabled={alcanzado} onClick={agregarHoja}>
          {t.criterios.agregar}
        </button>
        {esRaiz && (
          <button type="button" className="btn-enlace" disabled={alcanzado} onClick={agregarGrupo}>
            {t.criterios.agregarGrupo}
          </button>
        )}
      </div>
    </div>
  );
}

/** Constructor de criterios con Y/O y un nivel de grupos (cv1_09, CC-REQ-100). */
export function ConstructorCriterios(props: Props) {
  const numeros = numerar(props.raiz);
  return (
    <div className="not-constructor">
      <GrupoVista grupo={props.raiz} raiz={props.raiz} props={props} numeros={numeros} esRaiz />
      <p className="not-suave">{t.criterios.agregarAyuda}</p>
    </div>
  );
}
