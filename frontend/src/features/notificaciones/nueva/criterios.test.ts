import { describe, expect, it } from "vitest";
import {
  aCriterios,
  construirCatalogo,
  contarHojas,
  desdeCriterios,
  describirCriterios,
  esGrupo,
  grupoInicial,
  hojaVacia,
  MAX_CRITERIOS,
  rutasDe,
  type Grupo,
  type Hoja,
} from "./criterios";

const catalogo = construirCatalogo(
  [{ id: 1, nombre: "ORG01" }],
  [{ id: 2, nombre: "Apodaca" }],
  [
    { codigo_interno: "CAMP-0001", nombre_campo: "Área", tipo_dato: "LISTA", activo: true, es_sensible: false, opciones: [{ valor: "PRODUCCION", etiqueta: "Producción", activo: true }, { valor: "VIEJA", etiqueta: "Vieja", activo: false }] },
    { codigo_interno: "CAMP-0005", nombre_campo: "Sueldo", tipo_dato: "NUMERO", activo: true, es_sensible: true },
    { codigo_interno: "CAMP-0009", nombre_campo: "Baja", tipo_dato: "SI_NO", activo: false, es_sensible: false },
    { codigo_interno: "CAMP-0010", nombre_campo: "Ingreso", tipo_dato: "FECHA", activo: true, es_sensible: false },
    { codigo_interno: "CAMP-0011", nombre_campo: "Apodo", tipo_dato: "TEXTO", activo: true, es_sensible: false },
    { codigo_interno: "CAMP-0012", nombre_campo: "Sindicalizado", tipo_dato: "SI_NO", activo: true, es_sensible: false },
  ],
);

const hoja = (p: Partial<Hoja>): Hoja => ({ ...hojaVacia(), ...p });
const grupo = (op: "Y" | "O", ...items: Grupo["items"]): Grupo => ({ clave: `g-${Math.random()}`, op, items });

describe("catálogo de criterios", () => {
  it("excluye campos sensibles e inactivos y opciones inactivas", () => {
    const codigos = catalogo.lista.map((d) => d.codigo);
    expect(codigos).toEqual(expect.arrayContaining(["organizacion_id", "planta_id", "tipo_empleado", "estatus", "antiguedad_anios", "CAMP-0001", "CAMP-0010", "CAMP-0011", "CAMP-0012"]));
    expect(codigos).not.toContain("CAMP-0005");
    expect(codigos).not.toContain("CAMP-0009");
    expect(codigos).not.toContain("colaborador_id");
    expect(catalogo.porCodigo.get("CAMP-0001")!.opciones!.map((o) => o.valor)).toEqual(["PRODUCCION"]);
  });
});

describe("aCriterios", () => {
  it("convierte cada tipo al valor del contrato", () => {
    const raiz = grupo(
      "Y",
      hoja({ campo: "organizacion_id", operador: "en", lista: ["1"] }),
      hoja({ campo: "estatus", operador: "no_es", v1: "BAJA" }),
      hoja({ campo: "antiguedad_anios", operador: "entre", v1: "2", v2: "9" }),
      hoja({ campo: "CAMP-0010", operador: "despues", v1: "2025-01-31" }),
      hoja({ campo: "CAMP-0011", operador: "contiene", v1: "  ana " }),
      hoja({ campo: "CAMP-0012", operador: "es", v1: "true" }),
      grupo("O", hoja({ campo: "CAMP-0001", operador: "en", lista: ["PRODUCCION"] })),
    );
    const { criterios, errores } = aCriterios(raiz, catalogo);
    expect(errores.size).toBe(0);
    expect(criterios).toEqual({
      op: "Y",
      items: [
        { campo: "organizacion_id", operador: "en", valor: [1] },
        { campo: "estatus", operador: "no_es", valor: "BAJA" },
        { campo: "antiguedad_anios", operador: "entre", valor: [2, 9] },
        { campo: "CAMP-0010", operador: "despues", valor: "2025-01-31" },
        { campo: "CAMP-0011", operador: "contiene", valor: "ana" },
        { campo: "CAMP-0012", operador: "es", valor: true },
        { op: "O", items: [{ campo: "CAMP-0001", operador: "en", valor: ["PRODUCCION"] }] },
      ],
    });
  });

  it("rechaza criterios vacíos, grupos vacíos y más de 20 criterios", () => {
    const vacia = aCriterios(grupoInicial(), catalogo);
    expect(vacia.criterios).toBeNull();
    expect([...vacia.errores.values()]).toEqual(["Indica un valor."]);

    const grupoVacio = grupo("Y", grupo("O"));
    const r = aCriterios(grupoVacio, catalogo);
    expect([...r.errores.values()]).toContain("Un grupo no puede estar vacío.");

    const muchos = grupo("Y", ...Array.from({ length: MAX_CRITERIOS + 1 }, () => hoja({ campo: "estatus", operador: "es", v1: "ACTIVO" })));
    expect(aCriterios(muchos, catalogo).errores.get(muchos.clave)).toBe("Máximo 20 criterios.");
  });
});

describe("lectura y descripción", () => {
  const guardados = {
    op: "O",
    items: [
      { campo: "planta_id", operador: "en", valor: [2] },
      { campo: "antiguedad_anios", operador: "entre", valor: [1, 4] },
      { op: "Y", items: [{ campo: "CAMP-0012", operador: "es", valor: false }] },
    ],
  };

  it("reconstruye el árbol de la pantalla y vuelve al mismo JSON", () => {
    const raiz = desdeCriterios(guardados);
    expect(raiz.op).toBe("O");
    expect(contarHojas(raiz)).toBe(3);
    expect(esGrupo(raiz.items[2]!)).toBe(true);
    expect(aCriterios(raiz, catalogo).criterios).toEqual(guardados);
    expect(rutasDe(raiz).get((raiz.items[2] as Grupo).items[0]!.clave)).toBe("criterios.items.2.items.0");
  });

  it("devuelve un árbol inicial si no hay criterios guardados", () => {
    expect(contarHojas(desdeCriterios(null))).toBe(1);
    expect(contarHojas(desdeCriterios({ op: "Y", items: [] }))).toBe(1);
  });

  it("describe los criterios con las etiquetas del catálogo", () => {
    expect(describirCriterios(guardados, catalogo)).toEqual([
      "Planta: es alguno de Apodaca",
      "Antigüedad (años): entre 1 y 4 años",
      "Sindicalizado: es No",
    ]);
  });
});
