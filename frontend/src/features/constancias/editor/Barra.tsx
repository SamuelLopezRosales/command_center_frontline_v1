import type { Editor } from "@tiptap/core";
import { useEditorState } from "@tiptap/react";
import { t } from "../textos";
import { TAMANOS_PT, normalizarColor } from "./serializar";

type Alin = "izquierda" | "centro" | "derecha" | "justificado";
const ALIN: { clave: Alin; tiptap: string; texto: string; etiqueta: string }[] = [
  { clave: "izquierda", tiptap: "left", texto: "Izq", etiqueta: t.barra.izquierda },
  { clave: "centro", tiptap: "center", texto: "Cen", etiqueta: t.barra.centro },
  { clave: "derecha", tiptap: "right", texto: "Der", etiqueta: t.barra.derecha },
  { clave: "justificado", tiptap: "justify", texto: "Just", etiqueta: t.barra.justificado },
];

const sinPerderSeleccion = (e: React.MouseEvent) => e.preventDefault();

/** Barra de formato: negrita, cursiva, subrayado, tamaño, alineación, color y logotipo. */
export function Barra({ editor }: { editor: Editor }) {
  const e = useEditorState({
    editor,
    selector: ({ editor: ed }) => {
      const estilo = ed.getAttributes("textStyle") as { fontSize?: string; color?: string };
      const logo = ed.isActive("logotipo");
      return {
        negrita: ed.isActive("bold"),
        cursiva: ed.isActive("italic"),
        subrayado: ed.isActive("underline"),
        tamano: String(Number.parseInt(estilo.fontSize ?? "", 10) || ""),
        color: normalizarColor(estilo.color) ?? "#000000",
        logo,
        alineacion: logo
          ? (ed.getAttributes("logotipo").alineacion as Alin)
          : (ALIN.find((a) => ed.isActive({ textAlign: a.tiptap }))?.clave ?? "izquierda"),
      };
    },
  });

  const alinear = (a: (typeof ALIN)[number]) => {
    if (e.logo) editor.chain().focus().updateAttributes("logotipo", { alineacion: a.clave }).run();
    else editor.chain().focus().setTextAlign(a.tiptap).run();
  };

  return (
    <div className="ed-barra" role="toolbar" aria-label={t.barra.aria}>
      <button type="button" className="ed-btn" aria-label={t.barra.negrita} aria-pressed={e.negrita} onMouseDown={sinPerderSeleccion} onClick={() => editor.chain().focus().toggleBold().run()}>
        <strong>B</strong>
      </button>
      <button type="button" className="ed-btn" aria-label={t.barra.cursiva} aria-pressed={e.cursiva} onMouseDown={sinPerderSeleccion} onClick={() => editor.chain().focus().toggleItalic().run()}>
        <em>I</em>
      </button>
      <button type="button" className="ed-btn" aria-label={t.barra.subrayado} aria-pressed={e.subrayado} onMouseDown={sinPerderSeleccion} onClick={() => editor.chain().focus().toggleUnderline().run()}>
        <u>U</u>
      </button>
      <select
        className="ed-tamano"
        aria-label={t.barra.tamano}
        value={e.tamano}
        onChange={(ev) => {
          const v = ev.target.value;
          if (v) editor.chain().focus().setFontSize(`${v}pt`).run();
          else editor.chain().focus().unsetFontSize().run();
        }}
      >
        <option value="">—</option>
        {TAMANOS_PT.map((n) => (
          <option key={n} value={String(n)}>
            {n} pt
          </option>
        ))}
      </select>
      {ALIN.map((a) => (
        <button key={a.clave} type="button" className="ed-btn ed-btn-texto" aria-label={a.etiqueta} aria-pressed={e.alineacion === a.clave} onMouseDown={sinPerderSeleccion} onClick={() => alinear(a)}>
          {a.texto}
        </button>
      ))}
      <input
        type="color"
        className="ed-color"
        aria-label={t.barra.color}
        value={e.color}
        onChange={(ev) => editor.chain().focus().setColor(ev.target.value).run()}
      />
      <button type="button" className="ed-btn-logotipo" onMouseDown={sinPerderSeleccion} onClick={() => editor.chain().focus().insertarLogotipo().run()}>
        {t.barra.logotipo}
      </button>
    </div>
  );
}
