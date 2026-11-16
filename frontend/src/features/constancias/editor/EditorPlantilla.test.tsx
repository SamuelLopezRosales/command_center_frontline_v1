import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { RutasConstancias } from "../RutasConstancias";
import { CONTENIDO, VARIABLES, VERSIONES, plantilla } from "../test/datos";
import { json, parchearJsdom, problema, simulador, type Llamada } from "../test/simulador";
import { esperarAccesible } from "@/test/axe";

beforeAll(parchearJsdom);
afterEach(() => vi.unstubAllGlobals());

const base = (extra: Record<string, unknown> = {}) => ({
  "GET /api/v1/plantillas/7": () => json(plantilla()),
  "GET /api/v1/constancias/variables": { items: VARIABLES },
  "GET /api/v1/plantillas/7/borrador": () =>
    json({ contenido: CONTENIDO, hash: "abc", fecha_modificacion: "2026-11-12T18:00:00Z" }, 200, { ETag: '"abc"' }),
  "GET /api/v1/plantillas/7/versiones": { items: VERSIONES },
  "PUT /api/v1/plantillas/7/borrador": () => json({ hash: "def", fecha_modificacion: "2026-11-13T18:00:00Z" }, 200, { ETag: '"def"' }),
  "POST /api/v1/plantillas/7/borrador/validar": { errores: [], advertencias: [] },
  ...extra,
});

const montar = () =>
  renderizar(
    <Routes>
      <Route path="constancias/*" element={<RutasConstancias />} />
    </Routes>,
    { ruta: "/constancias/7" },
  );

const de = (llamadas: Llamada[], metodo: string, ruta: string) => llamadas.filter((l) => l.metodo === metodo && l.ruta === ruta);

describe("editor de plantilla (cv1_06)", () => {
  it("carga el borrador en el editor con el catálogo de variables y el estado de la plantilla", async () => {
    simulador(base());
    montar();
    expect(await screen.findByDisplayValue("Constancia laboral")).toBeInTheDocument();
    expect(await screen.findByText(/última versión publicada v3 \(12 nov 2026\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publicar v4" })).toBeInTheDocument();
    const documento = await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    expect(documento).toHaveTextContent("Hace constar que");
    expect(documento.querySelector('[data-variable="rfc"]')).toHaveClass("ed-variable-sensible");
    expect(documento.querySelector(".ed-logotipo")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Variables" })).getByRole("button", { name: "Insertar variable nss" })).toBeInTheDocument();
  });

  it("guarda el borrador con If-Match y usa el ETag nuevo en el siguiente guardado", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(base());
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await usuario.click(screen.getByRole("button", { name: "Guardar borrador" }));
    expect(await screen.findByText("Borrador guardado.")).toBeInTheDocument();
    const [primero] = de(llamadas, "PUT", "/api/v1/plantillas/7/borrador");
    expect(primero!.encabezados["If-Match"]).toBe('"abc"');
    expect(primero!.cuerpo).toMatchObject({
      esquema: 1,
      pagina: { tamano: "CARTA" },
      bloques: [
        { tipo: "logotipo", alineacion: "izquierda", ancho_cm: 5 },
        { tipo: "parrafo", alineacion: "centro", contenido: [{ texto: "Hace constar que " }, { var: "nombre_completo", negrita: true }, { texto: ", con RFC " }, { var: "rfc" }] },
      ],
    });

    await usuario.click(screen.getByRole("button", { name: "Guardar borrador" }));
    await waitFor(() => expect(de(llamadas, "PUT", "/api/v1/plantillas/7/borrador")).toHaveLength(2));
    expect(de(llamadas, "PUT", "/api/v1/plantillas/7/borrador")[1]!.encabezados["If-Match"]).toBe('"def"');
  });

  it("si el borrador cambió (412) avisa y ofrece recargar", async () => {
    const usuario = userEvent.setup();
    simulador(base({ "PUT /api/v1/plantillas/7/borrador": () => problema(412, "VERSION_DESACTUALIZADA", "El borrador cambió") }));
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await usuario.click(screen.getByRole("button", { name: "Guardar borrador" }));
    expect(await screen.findByText(/El borrador cambió desde que lo abriste/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recargar borrador" })).toBeInTheDocument();
  });

  it("insertar una variable marca cambios sin guardar y se guarda como nodo de variable", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(base());
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    expect(screen.queryByText(/Cambios sin guardar/)).not.toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Insertar variable puesto" }));
    expect(await screen.findByText(/Cambios sin guardar/)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Guardar borrador" }));
    await waitFor(() => expect(de(llamadas, "PUT", "/api/v1/plantillas/7/borrador")).toHaveLength(1));
    expect(JSON.stringify(de(llamadas, "PUT", "/api/v1/plantillas/7/borrador")[0]!.cuerpo)).toContain('{"var":"puesto"}');
  });

  it("sin borrador parte de la última versión publicada y guarda sin If-Match", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(
      base({
        "GET /api/v1/plantillas/7/borrador": () => problema(404, "BORRADOR_NO_EXISTE", "La plantilla todavía no tiene borrador."),
        "GET /api/v1/plantillas/7/versiones/3": () => json({ ...VERSIONES[0], contenido: CONTENIDO }),
      }),
    );
    montar();
    expect(await screen.findByText(/se cargó la última versión publicada como punto de partida/)).toBeInTheDocument();
    expect(await screen.findByText(/Cambios sin guardar/)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Guardar borrador" }));
    await waitFor(() => expect(de(llamadas, "PUT", "/api/v1/plantillas/7/borrador")).toHaveLength(1));
    expect(de(llamadas, "PUT", "/api/v1/plantillas/7/borrador")[0]!.encabezados["If-Match"]).toBeUndefined();
  });
});

describe("vista previa, validación y publicación del editor", () => {
  it("la vista previa va en un iframe con sandbox sin scripts ni mismo origen", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(
      base({
        "GET /api/v1/colaboradores": { items: [{ id: 41, nombre_completo: "Samuel López Rosales" }], total: 1, pagina: 1, limite: 5 },
        "POST /api/v1/plantillas/7/vista-previa": {
          html: '<html><body><p>Constancia</p><script>alert(1)</script></body></html>',
          faltantes: ["nss"],
          desconocidas: [],
        },
      }),
    );
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await usuario.click(screen.getByRole("button", { name: "Ver vista previa" }));
    expect(await screen.findByText("Elige un colaborador de prueba.")).toBeInTheDocument();

    await usuario.type(screen.getByLabelText("Colaborador de prueba"), "Sam");
    await usuario.click(await screen.findByRole("button", { name: "Samuel López Rosales" }));
    await usuario.click(screen.getByRole("button", { name: "Ver vista previa" }));

    const marco = (await screen.findByTitle("Vista previa de la constancia")) as HTMLIFrameElement;
    expect(marco.tagName).toBe("IFRAME");
    expect(marco).toHaveAttribute("sandbox");
    const permisos = marco.getAttribute("sandbox")!;
    expect(permisos).not.toContain("allow-scripts");
    expect(permisos).not.toContain("allow-same-origin");
    expect(marco.getAttribute("srcdoc")).toContain("<p>Constancia</p>");
    // El HTML de la API nunca se inserta en la página, solo en el iframe.
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("Datos faltantes para este colaborador: nss.")).toBeInTheDocument();
    expect(de(llamadas, "POST", "/api/v1/plantillas/7/vista-previa")[0]!.cuerpo).toEqual({ colaborador_id: 41, usar_borrador: true });
  });

  it("el panel de validación muestra errores y avisos", async () => {
    const usuario = userEvent.setup();
    simulador(
      base({
        "POST /api/v1/plantillas/7/borrador/validar": {
          errores: [{ codigo: "VARIABLE_INEXISTENTE", mensaje: "La variable no existe.", variables: ["sueldo_x"] }],
          advertencias: [
            { codigo: "VARIABLES_SENSIBLES", mensaje: "La plantilla usa datos sensibles: aparecerán en las constancias.", variables: ["rfc", "nss"] },
            { codigo: "COLABORADORES_SIN_VALOR", mensaje: "2 colaboradores sin NSS.", variables: ["nss"], total: 2 },
          ],
        },
      }),
    );
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    expect(screen.getByText("Aún no se ha validado el borrador.")).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Validar" }));
    const panel = await screen.findByRole("region", { name: "Validación" });
    expect(await within(panel).findByText("La variable no existe.")).toBeInTheDocument();
    expect(within(panel).getByText("(sueldo_x)")).toBeInTheDocument();
    expect(within(panel).getByText("Error")).toBeInTheDocument();
    expect(within(panel).getAllByText("Aviso")).toHaveLength(2);
    expect(within(panel).getByText("2 colaboradores sin NSS.")).toBeInTheDocument();
  });

  it("guardar el borrador lo valida; sin hallazgos muestra OK", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(base());
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await usuario.click(screen.getByRole("button", { name: "Guardar borrador" }));
    const panel = await screen.findByRole("region", { name: "Validación" });
    expect(await within(panel).findByText("Sin errores: todas las variables son válidas.")).toBeInTheDocument();
    expect(de(llamadas, "POST", "/api/v1/plantillas/7/borrador/validar")).toHaveLength(1);
  });

  it("publicar con variables sensibles pide confirmación y envía confirmar_sensibles", async () => {
    const usuario = userEvent.setup();
    let intentos = 0;
    const llamadas = simulador(
      base({
        "POST /api/v1/plantillas/7/publicar": () => {
          intentos += 1;
          return intentos === 1
            ? problema(409, "PLANTILLA_SENSIBLES_REQUIERE_CONFIRMACION", "La plantilla usa datos sensibles; confirme la publicación.")
            : json({ numero: 4, hash: "h4", fecha_creacion: "2026-11-14T18:00:00Z", vigente: true }, 201);
        },
      }),
    );
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await usuario.click(screen.getByRole("button", { name: "Publicar v4" }));

    const dialogo = await screen.findByRole("dialog", { name: "Confirma el uso de datos sensibles" });
    expect(within(dialogo).getByText("{{rfc}}")).toBeInTheDocument();
    expect(within(dialogo).queryByText("{{nombre_completo}}")).not.toBeInTheDocument();
    expect(de(llamadas, "POST", "/api/v1/plantillas/7/publicar")[0]!.cuerpo).toEqual({ confirmar_sensibles: false });

    await usuario.click(within(dialogo).getByRole("button", { name: "Confirmar y publicar" }));
    expect(await screen.findByText("Se publicó la versión v4.")).toBeInTheDocument();
    expect(de(llamadas, "POST", "/api/v1/plantillas/7/publicar")[1]!.cuerpo).toEqual({ confirmar_sensibles: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancelar la confirmación no publica", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(
      base({ "POST /api/v1/plantillas/7/publicar": () => problema(409, "PLANTILLA_SENSIBLES_REQUIERE_CONFIRMACION", "Confirme.") }),
    );
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await usuario.click(screen.getByRole("button", { name: "Publicar v4" }));
    await usuario.click(await screen.findByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(de(llamadas, "POST", "/api/v1/plantillas/7/publicar")).toHaveLength(1);
  });

  it("publicar con variables inválidas muestra el error y revalida", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(
      base({ "POST /api/v1/plantillas/7/publicar": () => problema(422, "PLANTILLA_VARIABLE_INVALIDA", "Hay variables que no existen o están desactivadas.") }),
    );
    montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await usuario.click(screen.getByRole("button", { name: "Publicar v4" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Hay variables que no existen o están desactivadas.");
    await waitFor(() => expect(de(llamadas, "POST", "/api/v1/plantillas/7/borrador/validar")).toHaveLength(1));
  });
});

describe("versiones", () => {
  it("lista las versiones con la activa marcada y Restaurar en las demás", async () => {
    simulador(base());
    montar();
    const panel = await screen.findByRole("region", { name: "Versiones" });
    const items = await within(panel).findAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("v3 · 12 nov 2026");
    expect(within(items[0]!).getByText("Activa")).toBeInTheDocument();
    expect(within(items[0]!).queryByRole("button")).not.toBeInTheDocument();
    expect(within(items[1]!).getByRole("button", { name: "Restaurar v2" })).toBeInTheDocument();
    expect(within(items[2]!).getByRole("button", { name: "Restaurar v1" })).toBeInTheDocument();
  });

  it("restaurar crea una versión nueva y recarga la lista", async () => {
    const usuario = userEvent.setup();
    let restaurada = false;
    const llamadas = simulador(
      base({
        "POST /api/v1/plantillas/7/versiones/2/restaurar": () => {
          restaurada = true;
          return json({ numero: 4, hash: "h4", fecha_creacion: "2026-11-14T18:00:00Z", vigente: true }, 201);
        },
        "GET /api/v1/plantillas/7/versiones": () =>
          json({
            items: restaurada
              ? [{ numero: 4, hash: "h4", fecha_creacion: "2026-11-14T18:00:00Z", vigente: true }, ...VERSIONES.map((v) => ({ ...v, vigente: false }))]
              : VERSIONES,
          }),
      }),
    );
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Restaurar v2" }));
    expect(await screen.findByText("La versión v2 se restauró como la versión nueva v4.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Restaurar v3" })).toBeInTheDocument());
    expect(de(llamadas, "POST", "/api/v1/plantillas/7/versiones/2/restaurar")).toHaveLength(1);
    // Restaurar no toca el borrador.
    expect(de(llamadas, "PUT", "/api/v1/plantillas/7/borrador")).toHaveLength(0);
  });

  it("informa si la restauración falla (variable que dejó de existir)", async () => {
    const usuario = userEvent.setup();
    simulador(
      base({ "POST /api/v1/plantillas/7/versiones/1/restaurar": () => problema(422, "PLANTILLA_VARIABLE_INVALIDA", "Hay variables que no existen o están desactivadas.") }),
    );
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Restaurar v1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Hay variables que no existen");
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el editor de plantilla no tiene violaciones críticas ni serias de axe", async () => {
    simulador(base());
    const { container } = montar();
    await screen.findByRole("textbox", { name: "Contenido de la constancia" });
    await screen.findByText(/última versión publicada v3/);
    await esperarAccesible(container);
  });
});
