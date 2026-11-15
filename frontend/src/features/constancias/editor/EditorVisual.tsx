import type { Editor, JSONContent } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useMemo } from "react";
import type { Contenido, Variable } from "../api";
import { t } from "../textos";
import { Barra } from "./Barra";
import { extensionesEditor } from "./extensiones";
import { PanelVariables } from "./PanelVariables";
import { contenidoADoc } from "./serializar";

interface Props {
  /** Contenido inicial: el editor se crea una vez con él. */
  contenido: Contenido;
  variables: Variable[];
  alCambiar: (doc: JSONContent) => void;
  /** Entrega la instancia (para que la pantalla pueda leer el documento). */
  alCrear?: (editor: Editor) => void;
}

/** Variables sensibles de un catálogo, para resaltarlas en el documento. */
export function nombresSensibles(variables: Variable[]): Set<string> {
  return new Set(variables.filter((v) => v.sensible || v.grupo === "SENSIBLES").map((v) => v.nombre));
}

/** Panel de variables, barra de formato y hoja del documento (cv1_06). */
export function EditorVisual({ contenido, variables, alCambiar, alCrear }: Props) {
  const inicial = useMemo(() => contenidoADoc(contenido, nombresSensibles(variables)), []); // eslint-disable-line react-hooks/exhaustive-deps
  const editor = useEditor({
    extensions: extensionesEditor(),
    content: inicial,
    editorProps: {
      attributes: { role: "textbox", "aria-multiline": "true", "aria-label": t.editor.contenido, class: "ed-documento" },
    },
    onUpdate: ({ editor: ed }) => alCambiar(ed.getJSON()),
  });

  useEffect(() => {
    if (editor && alCrear) alCrear(editor);
  }, [editor, alCrear]);

  if (!editor) return null;

  const insertar = (v: Variable) => {
    const sensible = v.sensible || v.grupo === "SENSIBLES";
    editor.chain().focus().insertarVariable(v.nombre, sensible).run();
  };

  return (
    <div className="ed-cuerpo">
      <PanelVariables variables={variables} alInsertar={insertar} />
      <div className="ed-centro">
        <Barra editor={editor} />
        <div className="ed-hoja" aria-label={t.editor.hoja}>
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  );
}
