// Modelo del constructor de criterios (design.md §6.1). El formato y la lista cerrada de operadores
// salen de `services/shared/cc_common/criterios_audiencia.py`: raíz siempre grupo, profundidad 2 y
// máximo 20 criterios. Solo campos activos y NO sensibles.
import { t } from "../textos";

export const MAX_CRITERIOS = 20;
export const ANTIGUEDAD_MAX = 80;

export type TipoCriterio = "ID" | "ENUM" | "ANTIGUEDAD" | "TEXTO" | "NUMERO" | "FECHA" | "LISTA" | "SI_NO";
export interface Opcion {
  valor: string;
  etiqueta: string;
}
export interface DefCriterio {
  codigo: string;
  etiqueta: string;
  tipo: TipoCriterio;
  opciones?: Opcion[];
}

export interface Hoja {
  clave: string;
  campo: string;
  operador: string;
  v1: string;
  v2: string;
  lista: string[];
}
export interface Grupo {
  clave: string;
  op: "Y" | "O";
  items: (Hoja | Grupo)[];
}
export type Nodo = Hoja | Grupo;
export const esGrupo = (n: Nodo): n is Grupo => "items" in n;

let contador = 0;
export const nuevaClave = () => `c${++contador}`;

export const hojaVacia = (): Hoja => ({ clave: nuevaClave(), campo: "", operador: "", v1: "", v2: "", lista: [] });
export const grupoInicial = (): Grupo => ({ clave: nuevaClave(), op: "Y", items: [hojaVacia()] });
export const grupoNuevo = (): Grupo => ({ clave: nuevaClave(), op: "Y", items: [hojaVacia()] });

const OPERADORES: Record<TipoCriterio, string[]> = {
  ID: ["es", "no_es", "en"],
  ENUM: ["es", "no_es", "en"],
  LISTA: ["es", "no_es", "en"],
  ANTIGUEDAD: ["=", "<", "<=", ">", ">=", "entre"],
  NUMERO: ["=", "<", "<=", ">", ">=", "entre"],
  TEXTO: ["es", "no_es", "contiene"],
  FECHA: ["antes", "despues", "entre"],
  SI_NO: ["es"],
};
export const operadoresDe = (tipo: TipoCriterio) => OPERADORES[tipo];
export const usaOpciones = (tipo: TipoCriterio) => tipo === "ID" || tipo === "ENUM" || tipo === "LISTA";

export function contarHojas(g: Grupo): number {
  return g.items.reduce((n, i) => n + (esGrupo(i) ? contarHojas(i) : 1), 0);
}

/** Ruta del servidor (`criterios.items.0.items.1`) de cada nodo, para mostrar sus errores. */
export function rutasDe(raiz: Grupo): Map<string, string> {
  const m = new Map<string, string>();
  const rec = (g: Grupo, ruta: string) => {
    m.set(g.clave, ruta);
    g.items.forEach((i, idx) => {
      const r = `${ruta}.items.${idx}`;
      if (esGrupo(i)) rec(i, r);
      else m.set(i.clave, r);
    });
  };
  rec(raiz, "criterios");
  return m;
}

export interface Catalogo {
  porCodigo: Map<string, DefCriterio>;
  lista: DefCriterio[];
}

export function construirCatalogo(
  organizaciones: { id: number; nombre: string }[],
  plantas: { id: number; nombre: string }[],
  dinamicos: {
    codigo_interno: string;
    nombre_campo: string;
    tipo_dato: "TEXTO" | "NUMERO" | "FECHA" | "LISTA" | "SI_NO";
    activo: boolean;
    es_sensible: boolean;
    opciones?: { valor: string; etiqueta: string; activo: boolean }[] | null;
  }[],
): Catalogo {
  const fijos: DefCriterio[] = [
    { codigo: "organizacion_id", etiqueta: t.criterios.campos.organizacion_id!, tipo: "ID", opciones: organizaciones.map((o) => ({ valor: String(o.id), etiqueta: o.nombre })) },
    { codigo: "planta_id", etiqueta: t.criterios.campos.planta_id!, tipo: "ID", opciones: plantas.map((p) => ({ valor: String(p.id), etiqueta: p.nombre })) },
    {
      codigo: "tipo_empleado",
      etiqueta: t.criterios.campos.tipo_empleado!,
      tipo: "ENUM",
      opciones: ["ADMINISTRATIVO", "OPERATIVO"].map((v) => ({ valor: v, etiqueta: t.criterios.enumeraciones[v]! })),
    },
    {
      codigo: "estatus",
      etiqueta: t.criterios.campos.estatus!,
      tipo: "ENUM",
      opciones: ["ACTIVO", "BAJA"].map((v) => ({ valor: v, etiqueta: t.criterios.enumeraciones[v]! })),
    },
    { codigo: "antiguedad_anios", etiqueta: t.criterios.campos.antiguedad_anios!, tipo: "ANTIGUEDAD" },
  ];
  const extra: DefCriterio[] = dinamicos
    .filter((d) => d.activo && !d.es_sensible)
    .map((d) => ({
      codigo: d.codigo_interno,
      etiqueta: d.nombre_campo,
      tipo: d.tipo_dato,
      opciones: d.tipo_dato === "LISTA" ? (d.opciones ?? []).filter((o) => o.activo).map((o) => ({ valor: o.valor, etiqueta: o.etiqueta })) : undefined,
    }));
  const lista = [...fijos, ...extra];
  return { lista, porCodigo: new Map(lista.map((d) => [d.codigo, d])) };
}

// ---------------------------------------------------------------------------- serialización

type Valor = string | number | boolean | (string | number)[];

function valorDe(def: DefCriterio, h: Hoja): Valor {
  const uno = (v: string): string | number | boolean => {
    switch (def.tipo) {
      case "ID":
      case "ANTIGUEDAD":
      case "NUMERO":
        return Number(v);
      case "SI_NO":
        return v === "true";
      case "TEXTO":
        return v.trim();
      default:
        return v;
    }
  };
  if (h.operador === "en") return h.lista.map((v) => uno(v) as string | number);
  if (h.operador === "entre") return [uno(h.v1) as string | number, uno(h.v2) as string | number];
  return uno(h.v1) as Valor;
}

export interface ResultadoCriterios {
  criterios: Record<string, unknown> | null;
  /** Errores locales por clave de nodo (hoja o grupo). */
  errores: Map<string, string>;
}

/** Valida en pantalla y arma el JSON del contrato. Un error local impide guardar. */
export function aCriterios(raiz: Grupo, catalogo: Catalogo): ResultadoCriterios {
  const errores = new Map<string, string>();
  const total = contarHojas(raiz);
  if (total === 0) errores.set(raiz.clave, t.criterios.sinCriterios);
  if (total > MAX_CRITERIOS) errores.set(raiz.clave, t.criterios.maximo);

  const hoja = (h: Hoja) => {
    const def = catalogo.porCodigo.get(h.campo);
    if (!def) {
      errores.set(h.clave, t.criterios.valorRequerido);
      return null;
    }
    const vacio =
      h.operador === "en" ? h.lista.length === 0 : h.operador === "entre" ? !h.v1.trim() || !h.v2.trim() : !h.v1.trim();
    if (!h.operador || vacio) {
      errores.set(h.clave, t.criterios.valorRequerido);
      return null;
    }
    if (def.tipo === "ANTIGUEDAD" || def.tipo === "NUMERO") {
      const nums = h.operador === "entre" ? [h.v1, h.v2] : [h.v1];
      if (nums.some((n) => !Number.isFinite(Number(n)))) {
        errores.set(h.clave, t.criterios.valorNumerico);
        return null;
      }
      if (def.tipo === "ANTIGUEDAD" && nums.some((n) => !Number.isInteger(Number(n)) || Number(n) < 0 || Number(n) > ANTIGUEDAD_MAX)) {
        errores.set(h.clave, t.criterios.antiguedadRango);
        return null;
      }
      if (h.operador === "entre" && Number(h.v1) > Number(h.v2)) {
        errores.set(h.clave, t.criterios.rangoInvertido);
        return null;
      }
    }
    if (h.operador === "entre" && def.tipo === "FECHA" && h.v1 > h.v2) {
      errores.set(h.clave, t.criterios.rangoInvertido);
      return null;
    }
    return { campo: h.campo, operador: h.operador, valor: valorDe(def, h) };
  };

  const grupo = (g: Grupo): Record<string, unknown> | null => {
    if (g.items.length === 0) {
      errores.set(g.clave, t.criterios.grupoVacio);
      return null;
    }
    const items = g.items.map((i) => (esGrupo(i) ? grupo(i) : hoja(i)));
    return items.some((i) => i === null) ? null : { op: g.op, items };
  };

  const criterios = grupo(raiz);
  return { criterios: errores.size > 0 ? null : criterios, errores };
}

// ---------------------------------------------------------------------------- lectura

function hojaDeJson(n: Record<string, unknown>): Hoja {
  const h = { ...hojaVacia(), campo: String(n.campo ?? ""), operador: String(n.operador ?? "") };
  const v = n.valor;
  const txt = (x: unknown) => (typeof x === "boolean" ? String(x) : String(x ?? ""));
  if (Array.isArray(v)) {
    if (h.operador === "entre") {
      h.v1 = txt(v[0]);
      h.v2 = txt(v[1]);
    } else {
      h.lista = v.map(txt);
    }
  } else {
    h.v1 = txt(v);
  }
  return h;
}

/** Reconstruye el árbol de la pantalla a partir de los criterios guardados en el borrador. */
export function desdeCriterios(json: unknown): Grupo {
  const nodo = (n: unknown): Nodo | null => {
    if (!n || typeof n !== "object") return null;
    const o = n as Record<string, unknown>;
    if (Array.isArray(o.items)) {
      const items = o.items.map(nodo).filter((x): x is Nodo => x !== null);
      return { clave: nuevaClave(), op: o.op === "O" ? "O" : "Y", items };
    }
    return hojaDeJson(o);
  };
  const raiz = nodo(json);
  return raiz && esGrupo(raiz) && raiz.items.length > 0 ? raiz : grupoInicial();
}

// ---------------------------------------------------------------------------- descripción

/** Etiquetas legibles de los criterios guardados (tarjeta «Audiencia» del detalle). */
export function describirCriterios(json: unknown, catalogo: Catalogo): string[] {
  const salida: string[] = [];
  const rec = (n: unknown) => {
    if (!n || typeof n !== "object") return;
    const o = n as Record<string, unknown>;
    if (Array.isArray(o.items)) {
      o.items.forEach(rec);
      return;
    }
    const campo = String(o.campo ?? "");
    const def = catalogo.porCodigo.get(campo);
    const etiqueta = def?.etiqueta ?? t.criterios.campos[campo] ?? (campo === "colaborador_id" ? "Colaborador" : campo);
    const nombreValor = (x: unknown) => {
      const s = typeof x === "boolean" ? (x ? t.criterios.si : t.criterios.no) : String(x);
      return def?.opciones?.find((op) => op.valor === s)?.etiqueta ?? t.criterios.enumeraciones[s] ?? s;
    };
    const v = o.valor;
    const valor = Array.isArray(v) ? v.map(nombreValor).join(o.operador === "entre" ? " y " : ", ") : nombreValor(v);
    const op = t.criterios.operadores[String(o.operador)] ?? String(o.operador);
    const sufijo = campo === "antiguedad_anios" ? ` ${t.criterios.sufijoAnios}` : "";
    salida.push(`${etiqueta}: ${op} ${valor}${sufijo}`);
  };
  rec(json);
  return salida;
}
