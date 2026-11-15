import { Node, mergeAttributes, nodeInputRule, type Extensions } from "@tiptap/core";
import { Color } from "@tiptap/extension-color";
import { TextAlign } from "@tiptap/extension-text-align";
import { FontSize, TextStyle } from "@tiptap/extension-text-style";
import StarterKit from "@tiptap/starter-kit";

export const PATRON_VARIABLE = /^[a-z][a-z0-9_]{0,40}(\.[a-z][a-z0-9_]{0,40})?$/;
const ESCRITA = /\{\{([a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40})?)\}\}$/;

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    variable: { insertarVariable: (nombre: string, sensible?: boolean) => ReturnType };
    logotipo: { insertarLogotipo: () => ReturnType };
  }
}

/** Nodo en línea y atómico: `{{nombre}}` se guarda como `{"var": "nombre"}` (design.md §5.1). */
export const Variable = Node.create({
  name: "variable",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      var: { default: "" },
      // Solo presentación (resaltado); no se serializa.
      sensible: { default: false, rendered: false },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-variable]", getAttrs: (el) => ({ var: (el as HTMLElement).getAttribute("data-variable") }) }];
  },
  renderHTML({ node, HTMLAttributes }) {
    const sensible = Boolean(node.attrs.sensible);
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-variable": node.attrs.var,
        class: sensible ? "ed-variable ed-variable-sensible" : "ed-variable",
      }),
      `{{${node.attrs.var}}}`,
    ];
  },
  renderText({ node }) {
    return `{{${node.attrs.var}}}`;
  },
  addCommands() {
    return {
      insertarVariable:
        (nombre, sensible = false) =>
        ({ commands }) =>
          PATRON_VARIABLE.test(nombre) && commands.insertContent({ type: this.name, attrs: { var: nombre, sensible } }),
    };
  },
  addInputRules() {
    // Lo que RH escribe como {{variable}} se convierte en nodo.
    return [nodeInputRule({ find: ESCRITA, type: this.type, getAttributes: (m) => ({ var: m[1] }) })];
  },
});

const CSS_ALINEACION: Record<string, string> = { izquierda: "left", centro: "center", derecha: "right", justificado: "left" };

/** Bloque del logotipo de la organización (CC-REQ-062): se resuelve al renderizar. */
export const Logotipo = Node.create({
  name: "logotipo",
  group: "block",
  atom: true,
  selectable: true,
  draggable: true,
  addAttributes() {
    return {
      alineacion: { default: "izquierda" },
      ancho_cm: { default: 5 },
    };
  },
  parseHTML() {
    return [{ tag: "div[data-logotipo]" }];
  },
  renderHTML({ node }) {
    return [
      "div",
      { "data-logotipo": "", class: "ed-logotipo", style: `text-align:${CSS_ALINEACION[String(node.attrs.alineacion)] ?? "left"}` },
      ["span", { class: "ed-logotipo-caja" }, "[Logotipo de la organización]"],
    ];
  },
  addCommands() {
    return {
      insertarLogotipo:
        () =>
        ({ commands }) =>
          commands.insertContent({ type: this.name }),
    };
  },
});

/** Solo lo que admite el esquema del contenido: sin encabezados, listas, enlaces ni HTML libre. */
export function extensionesEditor(): Extensions {
  return [
    StarterKit.configure({
      heading: false,
      blockquote: false,
      bulletList: false,
      orderedList: false,
      listItem: false,
      listKeymap: false,
      code: false,
      codeBlock: false,
      horizontalRule: false,
      strike: false,
      link: false,
      trailingNode: false,
    }),
    TextStyle,
    Color,
    FontSize,
    TextAlign.configure({ types: ["paragraph"] }),
    Variable,
    Logotipo,
  ];
}
