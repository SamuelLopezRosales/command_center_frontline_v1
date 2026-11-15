import { describe, expect, it } from "vitest";
import { CONTENIDO } from "../test/datos";
import { contenidoADoc, docAContenido, normalizarColor, variablesDelDoc } from "./serializar";

describe("serialización del editor al contenido de plantilla", () => {
  it("el contenido sobrevive ida y vuelta, incluidas variables y logotipo", () => {
    const doc = contenidoADoc(CONTENIDO);
    const vuelta = docAContenido(doc, CONTENIDO.pagina);
    expect(vuelta.bloques?.[0]).toEqual({ tipo: "logotipo", alineacion: "izquierda", ancho_cm: 5 });
    expect(vuelta.bloques?.[1]).toEqual({
      tipo: "parrafo",
      alineacion: "centro",
      contenido: [
        { texto: "Hace constar que " },
        { var: "nombre_completo", negrita: true },
        { texto: ", con RFC " },
        { var: "rfc" },
      ],
    });
    expect(vuelta.esquema).toBe(1);
    expect(vuelta.pagina).toEqual(CONTENIDO.pagina);
  });

  it("serializa tamaño en pt, color #RRGGBB, cursiva y subrayado", () => {
    const doc = contenidoADoc({
      esquema: 1,
      bloques: [{ tipo: "parrafo", alineacion: "derecha", contenido: [{ texto: "x", cursiva: true, subrayado: true, color: "#FF0000", tamano_pt: 14 }] }],
    });
    const salida = docAContenido(doc);
    expect(salida.bloques?.[0]).toMatchObject({ alineacion: "derecha", contenido: [{ texto: "x", cursiva: true, subrayado: true, color: "#ff0000", tamano_pt: 14 }] });
  });

  it("un salto de línea se guarda como nodo de salto y un párrafo vacío queda sin texto", () => {
    const salida = docAContenido({
      type: "doc",
      content: [
        { type: "paragraph", content: [{ type: "text", text: "a" }, { type: "hardBreak" }, { type: "text", text: "b" }] },
        { type: "paragraph" },
      ],
    });
    expect(salida.bloques?.[0]).toMatchObject({ contenido: [{ texto: "a" }, { salto: true }, { texto: "b" }] });
    expect(salida.bloques?.[1]).toMatchObject({ tipo: "parrafo", contenido: [] });
  });

  it("limita el tamaño a 8-48 pt y normaliza colores", () => {
    const salida = docAContenido({
      type: "doc",
      content: [{ type: "paragraph", content: [{ type: "text", text: "a", marks: [{ type: "textStyle", attrs: { fontSize: "72pt", color: "rgb(255, 0, 0)" } }] }] }],
    });
    expect(salida.bloques?.[0]).toMatchObject({ contenido: [{ texto: "a", tamano_pt: 48, color: "#ff0000" }] });
    expect(normalizarColor("#abc")).toBe("#aabbcc");
    expect(normalizarColor("rojo")).toBeUndefined();
  });

  it("variablesDelDoc lista las variables sin repetir", () => {
    const doc = contenidoADoc({
      esquema: 1,
      bloques: [{ tipo: "parrafo", alineacion: "izquierda", contenido: [{ var: "rfc" }, { texto: " " }, { var: "rfc" }, { var: "puesto" }] }],
    });
    expect(variablesDelDoc(doc)).toEqual(["rfc", "puesto"]);
  });
});
