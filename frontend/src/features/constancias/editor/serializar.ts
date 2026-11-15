import type { JSONContent } from "@tiptap/core";
import type { components } from "@/api-client/generado/constancias";

type Esq = components["schemas"];
type Contenido = Esq["ContenidoPlantilla"];
type Pagina = Esq["Pagina"];
type Alineacion = Esq["BloqueParrafo"]["alineacion"];
type Inline = NonNullable<Esq["BloqueParrafo"]["contenido"]>[number];

const A_TIPTAP: Record<Alineacion, string> = { izquierda: "left", centro: "center", derecha: "right", justificado: "justify" };
const DE_TIPTAP: Record<string, Alineacion> = { left: "izquierda", center: "centro", right: "derecha", justify: "justificado" };
const MAX_TEXTO = 5000;

export const TAMANOS_PT = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48];

/** Acepta `#rgb`, `#rrggbb` y `rgb(r, g, b)`; devuelve `#rrggbb` en minúsculas o undefined. */
export function normalizarColor(valor: unknown): string | undefined {
  if (typeof valor !== "string") return undefined;
  const v = valor.trim().toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(v)) return v;
  if (/^#[0-9a-f]{3}$/.test(v)) return `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
  const m = /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/.exec(v);
  if (!m) return undefined;
  const partes = [m[1], m[2], m[3]].map((n) => Math.min(255, Number(n)).toString(16).padStart(2, "0"));
  return `#${partes.join("")}`;
}

function tamanoPt(valor: unknown): number | undefined {
  const m = typeof valor === "string" ? /^(\d+(?:\.\d+)?)\s*pt$/.exec(valor.trim()) : null;
  if (!m) return undefined;
  return Math.min(48, Math.max(8, Math.round(Number(m[1]))));
}

interface Formato {
  negrita?: boolean;
  cursiva?: boolean;
  subrayado?: boolean;
  color?: string;
  tamano_pt?: number;
}

function formatoDeMarcas(marcas: JSONContent["marks"]): Formato {
  const f: Formato = {};
  for (const m of marcas ?? []) {
    if (m.type === "bold") f.negrita = true;
    else if (m.type === "italic") f.cursiva = true;
    else if (m.type === "underline") f.subrayado = true;
    else if (m.type === "textStyle") {
      const color = normalizarColor(m.attrs?.color);
      if (color) f.color = color;
      const t = tamanoPt(m.attrs?.fontSize);
      if (t) f.tamano_pt = t;
    }
  }
  return f;
}

function inline(nodos: JSONContent[] | undefined): Inline[] {
  const salida: Inline[] = [];
  for (const n of nodos ?? []) {
    if (n.type === "text" && n.text) {
      const f = formatoDeMarcas(n.marks);
      for (let i = 0; i < n.text.length; i += MAX_TEXTO) salida.push({ texto: n.text.slice(i, i + MAX_TEXTO), ...f });
    } else if (n.type === "variable" && typeof n.attrs?.var === "string") {
      salida.push({ var: n.attrs.var, ...formatoDeMarcas(n.marks) });
    } else if (n.type === "hardBreak") {
      salida.push({ salto: true });
    }
  }
  return salida;
}

/** Documento del editor a contenido de plantilla (esquema 1). */
export function docAContenido(doc: JSONContent, pagina?: Pagina): Contenido {
  const bloques: NonNullable<Contenido["bloques"]> = [];
  for (const n of doc.content ?? []) {
    if (n.type === "logotipo") {
      bloques.push({
        tipo: "logotipo",
        alineacion: (n.attrs?.alineacion as Alineacion) ?? "izquierda",
        ancho_cm: Math.min(15, Math.max(1, Number(n.attrs?.ancho_cm ?? 5))),
      });
    } else if (n.type === "paragraph") {
      bloques.push({
        tipo: "parrafo",
        alineacion: DE_TIPTAP[String(n.attrs?.textAlign ?? "left")] ?? "izquierda",
        contenido: inline(n.content),
      });
    }
  }
  return { esquema: 1, ...(pagina ? { pagina } : {}), bloques };
}

function marcas(f: Formato): JSONContent["marks"] {
  const m: NonNullable<JSONContent["marks"]> = [];
  if (f.negrita) m.push({ type: "bold" });
  if (f.cursiva) m.push({ type: "italic" });
  if (f.subrayado) m.push({ type: "underline" });
  const estilo: Record<string, string> = {};
  if (f.color) estilo.color = f.color;
  if (f.tamano_pt) estilo.fontSize = `${f.tamano_pt}pt`;
  if (Object.keys(estilo).length) m.push({ type: "textStyle", attrs: estilo });
  return m.length ? m : undefined;
}

type ConFormato = { negrita?: boolean | null; cursiva?: boolean | null; subrayado?: boolean | null; color?: string | null; tamano_pt?: number | null };

function formatoDeNodo(n: ConFormato): Formato {
  return {
    negrita: !!n.negrita,
    cursiva: !!n.cursiva,
    subrayado: !!n.subrayado,
    color: n.color ?? undefined,
    tamano_pt: n.tamano_pt ?? undefined,
  };
}

/** Contenido de plantilla al documento del editor. `sensibles` resalta las variables sensibles. */
export function contenidoADoc(contenido: Contenido, sensibles: ReadonlySet<string> = new Set()): JSONContent {
  const content: JSONContent[] = [];
  for (const b of contenido.bloques ?? []) {
    if (b.tipo === "logotipo") {
      content.push({ type: "logotipo", attrs: { alineacion: b.alineacion ?? "izquierda", ancho_cm: b.ancho_cm ?? 5 } });
      continue;
    }
    const hijos: JSONContent[] = [];
    for (const n of b.contenido ?? []) {
      if ("texto" in n) {
        if (n.texto) hijos.push({ type: "text", text: n.texto, marks: marcas(formatoDeNodo(n)) });
      } else if ("var" in n) {
        hijos.push({ type: "variable", attrs: { var: n.var, sensible: sensibles.has(n.var) }, marks: marcas(formatoDeNodo(n)) });
      } else {
        hijos.push({ type: "hardBreak" });
      }
    }
    content.push({ type: "paragraph", attrs: { textAlign: A_TIPTAP[b.alineacion ?? "izquierda"] }, ...(hijos.length ? { content: hijos } : {}) });
  }
  if (content.length === 0) content.push({ type: "paragraph" });
  return { type: "doc", content };
}

/** Nombres de variables usados en un documento del editor (sin repetir, en orden). */
export function variablesDelDoc(doc: JSONContent): string[] {
  const vistas = new Set<string>();
  const recorrer = (n: JSONContent) => {
    if (n.type === "variable" && typeof n.attrs?.var === "string") vistas.add(n.attrs.var);
    n.content?.forEach(recorrer);
  };
  recorrer(doc);
  return [...vistas];
}
