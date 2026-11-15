import type { Editor, JSONContent } from "@tiptap/core";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { parchearJsdom } from "../test/simulador";
import { VARIABLES } from "../test/datos";
import { EditorVisual } from "./EditorVisual";
import { docAContenido } from "./serializar";

beforeAll(parchearJsdom);

const INICIAL = {
  esquema: 1 as const,
  bloques: [{ tipo: "parrafo" as const, alineacion: "izquierda" as const, contenido: [{ texto: "Hola mundo" }] }],
};

function montar() {
  let editor!: Editor;
  let ultimo: JSONContent | null = null;
  render(
    <EditorVisual
      contenido={INICIAL}
      variables={VARIABLES}
      alCambiar={(d) => {
        ultimo = d;
      }}
      alCrear={(e) => {
        editor = e;
      }}
    />,
  );
  return {
    editor: () => editor,
    contenido: () => docAContenido(ultimo ?? editor.getJSON()),
    seleccionarTodo: () => act(() => void editor.commands.selectAll()),
  };
}

describe("editor TipTap: formato", () => {
  it("aplica negrita, cursiva y subrayado a la selección", async () => {
    const usuario = userEvent.setup();
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    e.seleccionarTodo();
    await usuario.click(screen.getByRole("button", { name: "Negrita" }));
    await usuario.click(screen.getByRole("button", { name: "Cursiva" }));
    await usuario.click(screen.getByRole("button", { name: "Subrayado" }));
    expect(e.contenido().bloques?.[0]).toMatchObject({
      contenido: [{ texto: "Hola mundo", negrita: true, cursiva: true, subrayado: true }],
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Negrita" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("cambia el tamaño en puntos (8 a 48)", async () => {
    const usuario = userEvent.setup();
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    e.seleccionarTodo();
    const tamano = screen.getByRole("combobox", { name: "Tamaño del texto (pt)" });
    expect([...tamano.querySelectorAll("option")].map((o) => o.value)).toEqual(expect.arrayContaining(["8", "12", "48"]));
    await usuario.selectOptions(tamano, "14");
    expect(e.contenido().bloques?.[0]).toMatchObject({ contenido: [{ texto: "Hola mundo", tamano_pt: 14 }] });
  });

  it("alinea el párrafo a la izquierda, centro, derecha o justificado", async () => {
    const usuario = userEvent.setup();
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    await usuario.click(screen.getByRole("button", { name: "Centrar" }));
    expect(e.contenido().bloques?.[0]).toMatchObject({ alineacion: "centro" });
    await usuario.click(screen.getByRole("button", { name: "Alinear a la derecha" }));
    expect(e.contenido().bloques?.[0]).toMatchObject({ alineacion: "derecha" });
    await usuario.click(screen.getByRole("button", { name: "Justificar" }));
    expect(e.contenido().bloques?.[0]).toMatchObject({ alineacion: "justificado" });
  });

  it("aplica color #RRGGBB al texto seleccionado", async () => {
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    e.seleccionarTodo();
    fireEvent.change(screen.getByLabelText("Color del texto"), { target: { value: "#ff0000" } });
    expect(e.contenido().bloques?.[0]).toMatchObject({ contenido: [{ texto: "Hola mundo", color: "#ff0000" }] });
  });
});

describe("editor TipTap: variables y logotipo", () => {
  it("el panel agrupa las variables por colaborador, organización, sensibles y sistema", async () => {
    montar();
    const panel = await screen.findByRole("region", { name: "Variables" });
    const grupos = within(panel).getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(grupos).toEqual(["Colaborador", "Organización", "Sensibles", "Sistema"]);
    const sensibles = within(within(panel).getByRole("group", { name: "Sensibles" })).getAllByRole("button");
    expect(sensibles.map((b) => b.textContent)).toEqual(["{{rfc}}", "{{nss}}"]);
    expect(sensibles[0]).toHaveClass("ed-chip-sensible");
  });

  it("el buscador filtra por nombre y por etiqueta", async () => {
    const usuario = userEvent.setup();
    montar();
    const panel = await screen.findByRole("region", { name: "Variables" });
    await usuario.type(within(panel).getByRole("searchbox", { name: "Buscar variable" }), "razón");
    expect(within(panel).getAllByRole("button").map((b) => b.textContent)).toEqual(["{{organizacion.razon_social}}"]);
    await usuario.clear(within(panel).getByRole("searchbox"));
    await usuario.type(within(panel).getByRole("searchbox"), "zzz");
    expect(within(panel).getByText("Ninguna variable coincide.")).toBeInTheDocument();
  });

  it("insertar una variable crea un nodo (no texto) que se guarda como {var}", async () => {
    const usuario = userEvent.setup();
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    await usuario.click(screen.getByRole("button", { name: "Insertar variable puesto" }));
    await usuario.click(screen.getByRole("button", { name: "Insertar variable rfc" }));
    const nodos = document.querySelectorAll(".ed-documento [data-variable]");
    expect([...nodos].map((n) => n.getAttribute("data-variable"))).toEqual(["puesto", "rfc"]);
    expect(document.querySelector('[data-variable="rfc"]')).toHaveClass("ed-variable-sensible");
    const inline = (e.contenido().bloques?.[0] as { contenido: unknown[] }).contenido;
    expect(inline).toEqual(expect.arrayContaining([{ var: "puesto" }, { var: "rfc" }]));
  });

  it("insertar el logotipo agrega un bloque de logotipo", async () => {
    const usuario = userEvent.setup();
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    await usuario.click(screen.getByRole("button", { name: "Insertar logotipo" }));
    expect(document.querySelector(".ed-documento .ed-logotipo")).toBeInTheDocument();
    expect(e.contenido().bloques).toEqual(expect.arrayContaining([{ tipo: "logotipo", alineacion: "izquierda", ancho_cm: 5 }]));
  });

  it("el logotipo seleccionado se alinea desde la barra", async () => {
    const usuario = userEvent.setup();
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    await usuario.click(screen.getByRole("button", { name: "Insertar logotipo" }));
    let posicion = -1;
    e.editor().state.doc.descendants((n, p) => {
      if (n.type.name === "logotipo") posicion = p;
    });
    act(() => void e.editor().commands.setNodeSelection(posicion));
    await usuario.click(screen.getByRole("button", { name: "Centrar" }));
    expect(e.contenido().bloques).toEqual(expect.arrayContaining([{ tipo: "logotipo", alineacion: "centro", ancho_cm: 5 }]));
  });

  it("escribir {{variable}} la convierte en nodo", async () => {
    const e = montar();
    await waitFor(() => expect(e.editor()).toBeDefined());
    act(() => {
      e.editor().commands.focus("end");
      e.editor().commands.insertContent("{{puesto}");
      const { view } = e.editor();
      const { from, to } = view.state.selection;
      view.someProp("handleTextInput", (f) => f(view, from, to, "}", () => view.state.tr));
    });
    expect(document.querySelector('.ed-documento [data-variable="puesto"]')).toBeInTheDocument();
  });
});
