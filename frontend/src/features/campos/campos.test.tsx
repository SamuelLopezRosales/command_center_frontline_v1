import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar, simularApi } from "@/test/ayudantes";
import { CAMPO_BONO, CAMPO_TURNO, DINAMICOS, campo, json, listadoCampos, problema } from "@/test/fixturas220";
import { RutasCampos } from "./RutasCampos";
import { esperarAccesible } from "@/test/axe";

afterEach(() => vi.unstubAllGlobals());

const montar = () =>
  renderizar(
    <Routes>
      <Route path="campos/*" element={<RutasCampos />} />
    </Routes>,
    { ruta: "/campos" },
  );

const cuerpo = (init?: RequestInit) => JSON.parse(String(init?.body));

describe("configuración de campos (cv1_04)", () => {
  it("pestañas Todos, Sugeridos y Personalizados con su conteo y filtro", async () => {
    simularApi({ "/api/v1/campos": listadoCampos() });
    const u = userEvent.setup();
    montar();

    // 11 fijos + 6 dinámicos (5 sugeridos y 1 personalizado).
    expect(await screen.findByRole("tab", { name: "Todos (17)" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Sugeridos (5)" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Personalizados (1)" })).toBeInTheDocument();
    expect(screen.getByText("Bono de productividad")).toBeInTheDocument();
    expect(screen.getByText("{{area}}")).toBeInTheDocument();

    await u.click(screen.getByRole("tab", { name: "Sugeridos (5)" }));
    expect(screen.getByText("Área")).toBeInTheDocument();
    expect(screen.queryByText("Bono de productividad")).not.toBeInTheDocument();
    expect(screen.queryByText(/Campos fijos del sistema/)).not.toBeInTheDocument();

    await u.click(screen.getByRole("tab", { name: "Personalizados (1)" }));
    expect(screen.getByText("Bono de productividad")).toBeInTheDocument();
    expect(screen.queryByText("Área")).not.toBeInTheDocument();
  });

  it("los once campos fijos se listan y no se pueden editar", async () => {
    simularApi({ "/api/v1/campos": listadoCampos() });
    montar();
    expect(await screen.findByText("Campos fijos del sistema (11): no editables aquí")).toBeInTheDocument();
    const filas = document.querySelectorAll("tr[data-fijo]");
    expect(filas).toHaveLength(11);
    for (const f of Array.from(filas)) {
      expect(within(f as HTMLElement).queryByRole("button")).not.toBeInTheDocument();
      expect(within(f as HTMLElement).getByRole("checkbox")).toBeDisabled();
    }
    // Los dinámicos sí tienen botón Editar.
    expect(screen.getByRole("button", { name: "Editar Turno" })).toBeInTheDocument();
  });

  it("panel de edición: nombre, clave, código interno, tipo, opciones y casillas", async () => {
    simularApi({ "/api/v1/campos": listadoCampos() });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar Turno" }));

    const panel = screen.getByRole("complementary", { name: "Editar campo" });
    expect(within(panel).getByLabelText("Nombre visible")).toHaveValue("Turno");
    expect(within(panel).getByLabelText("Clave de variable")).toHaveValue("turno");
    expect(within(panel).getByLabelText("Tipo de dato")).toHaveValue("LISTA");
    // Campo sugerido: la clave y el tipo no cambian.
    expect(within(panel).getByLabelText("Clave de variable")).toBeDisabled();
    expect(within(panel).getByLabelText("Tipo de dato")).toBeDisabled();
    expect(within(panel).getByText("Código interno CAMP-0003 · no cambia")).toBeInTheDocument();
    expect(within(panel).getByText("Usada en 1 plantilla")).toBeInTheDocument();
    expect(within(panel).getByText("Matutino")).toBeInTheDocument();
    expect(within(panel).getByText("08:00 – 17:00")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Obligatorio")).not.toBeChecked();
    expect(within(panel).getByLabelText("Sensible (se cifra)")).not.toBeChecked();
    expect(within(panel).getByLabelText("Activo")).toBeChecked();
    expect(within(panel).getByText(/Sugerido · Lista/)).toBeInTheDocument();
  });

  it("guarda solo lo que cambió (PATCH) y avisa si no hay cambios", async () => {
    const llamadas = simularApi({
      "/api/v1/campos/3": (init?: RequestInit) => json({ ...CAMPO_TURNO, ...cuerpo(init) }),
      "/api/v1/campos": listadoCampos(),
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar Turno" }));
    await u.click(screen.getByRole("button", { name: "Guardar campo" }));
    expect(await screen.findByText("No hay cambios que guardar.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.init?.method === "PATCH")).toBe(false);

    await u.clear(screen.getByLabelText("Nombre visible"));
    await u.type(screen.getByLabelText("Nombre visible"), "Turno de trabajo");
    await u.click(screen.getByLabelText("Obligatorio"));
    await u.click(screen.getByRole("button", { name: "Guardar campo" }));
    await waitFor(() => expect(llamadas.some((l) => l.init?.method === "PATCH")).toBe(true));
    const patch = llamadas.find((l) => l.init?.method === "PATCH")!;
    expect(patch.url).toBe("/api/v1/campos/3");
    expect(cuerpo(patch.init)).toEqual({ nombre_campo: "Turno de trabajo", obligatorio: true });
    expect(await screen.findByText("Campo guardado.")).toBeInTheDocument();
  });

  it("cambiar la clave de un campo usado en plantillas pide confirmación y reenvía con confirmar", async () => {
    let intentos = 0;
    const usado = { ...CAMPO_BONO, usada_en_plantillas: 2 };
    const llamadas = simularApi({
      "/api/v1/campos/12": (init?: RequestInit) => {
        intentos += 1;
        const c = cuerpo(init);
        if (!c.confirmar)
          return problema(409, "CLAVE_EN_USO_REQUIERE_CONFIRMACION", "La clave se usa en plantillas; confirme el cambio.", {
            detalle: {
              plantillas: [
                { id: 1, nombre: "Constancia laboral" },
                { id: 2, nombre: "Constancia guardería" },
              ],
              total: 2,
            },
          });
        return json({ ...usado, clave: c.clave });
      },
      "/api/v1/campos": listadoCampos([...DINAMICOS.filter((c) => c.id !== 12), usado]),
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar Bono de productividad" }));
    expect(screen.getByText("Usada en 2 plantillas")).toBeInTheDocument();

    const clave = screen.getByLabelText("Clave de variable");
    await u.clear(clave);
    await u.type(clave, "bono_mensual");
    await u.click(screen.getByRole("button", { name: "Guardar campo" }));

    const aviso = await screen.findByRole("alertdialog", { name: "Esta clave se usa en plantillas" });
    expect(within(aviso).getByText("Constancia laboral")).toBeInTheDocument();
    expect(within(aviso).getByText("Constancia guardería")).toBeInTheDocument();
    expect(intentos).toBe(1);

    // Cancelar no envía nada más.
    await u.click(within(aviso).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(intentos).toBe(1);

    await u.click(screen.getByRole("button", { name: "Guardar campo" }));
    await u.click(await screen.findByRole("button", { name: "Confirmar cambio de clave" }));
    await waitFor(() => expect(intentos).toBe(3));
    const patches = llamadas.filter((l) => l.init?.method === "PATCH").map((l) => cuerpo(l.init));
    expect(patches[0]).toEqual({ clave: "bono_mensual" });
    expect(patches[2]).toEqual({ clave: "bono_mensual", confirmar: true });
    expect(await screen.findByText("Campo guardado.")).toBeInTheDocument();
  });

  it("crea un campo personalizado y valida el formato de la clave", async () => {
    const nuevo = campo({ id: 20, codigo_interno: "CAMP-0020", clave: "talla", nombre_campo: "Talla", es_sugerido: false, es_sensible: true });
    let creado = false;
    const llamadas = simularApi({
      "/api/v1/campos": (init?: RequestInit) => {
        if (init?.method === "POST") {
          creado = true;
          return json(nuevo, 201);
        }
        return json(listadoCampos(creado ? [...DINAMICOS, nuevo] : DINAMICOS));
      },
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "+ Nuevo campo" }));

    const panel = screen.getByRole("complementary", { name: "Nuevo campo" });
    await u.type(within(panel).getByLabelText("Nombre visible"), "Talla");
    await u.type(within(panel).getByLabelText("Clave de variable"), "Talla Uniforme");
    await u.click(within(panel).getByLabelText("Sensible (se cifra)"));
    await u.click(within(panel).getByRole("button", { name: "Guardar campo" }));
    expect(await within(panel).findByText(/La clave debe empezar con letra minúscula/)).toBeInTheDocument();
    expect(llamadas.some((l) => l.init?.method === "POST")).toBe(false);

    await u.clear(within(panel).getByLabelText("Clave de variable"));
    await u.type(within(panel).getByLabelText("Clave de variable"), "talla");
    await u.click(within(panel).getByRole("button", { name: "Guardar campo" }));
    await waitFor(() => expect(llamadas.some((l) => l.init?.method === "POST")).toBe(true));
    expect(cuerpo(llamadas.find((l) => l.init?.method === "POST")!.init)).toEqual({
      nombre_campo: "Talla",
      clave: "talla",
      tipo_dato: "TEXTO",
      formato_validacion: null,
      obligatorio: false,
      es_sensible: true,
    });
    // Tras crear, el panel pasa a edición del campo nuevo (código interno asignado por el servidor).
    expect(await screen.findByText("Código interno CAMP-0020 · no cambia")).toBeInTheDocument();
  });

  it("muestra los errores por campo del servidor (clave reservada)", async () => {
    simularApi({
      "/api/v1/campos": (init?: RequestInit) =>
        init?.method === "POST"
          ? problema(422, "CLAVE_RESERVADA", "Clave reservada", { errores: [{ campo: "clave", codigo: "CLAVE_RESERVADA", mensaje: "La clave está reservada." }] })
          : json(listadoCampos()),
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "+ Nuevo campo" }));
    await u.type(screen.getByLabelText("Nombre visible"), "Empresa");
    await u.type(screen.getByLabelText("Clave de variable"), "empresa");
    await u.click(screen.getByRole("button", { name: "Guardar campo" }));
    expect(await screen.findByText("La clave está reservada.")).toBeInTheDocument();
  });

  it("agrega una opción a un campo de tipo Lista y permite desactivarla", async () => {
    const llamadas = simularApi({
      "/api/v1/campos/3/opciones/31": (init?: RequestInit) => json({ ...CAMPO_TURNO.opciones![0], ...cuerpo(init) }),
      "/api/v1/campos/3/opciones": (init?: RequestInit) =>
        json({ id: 32, etiqueta: "Vespertino", valor: "VESPERTINO", descripcion: "14:00 – 22:00", orden: 2, activo: true, ...cuerpo(init) }, 201),
      "/api/v1/campos": listadoCampos(),
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar Turno" }));
    await u.click(screen.getByRole("button", { name: "+ Agregar opción" }));
    await u.type(screen.getByLabelText("Etiqueta de la opción"), "Vespertino");
    await u.type(screen.getByLabelText("Descripción (opcional)"), "14:00 – 22:00");
    await u.click(screen.getByRole("button", { name: "Guardar opción" }));
    await waitFor(() => expect(llamadas.some((l) => l.url === "/api/v1/campos/3/opciones" && l.init?.method === "POST")).toBe(true));
    expect(cuerpo(llamadas.find((l) => l.init?.method === "POST")!.init)).toEqual({
      etiqueta: "Vespertino",
      valor: "VESPERTINO",
      descripcion: "14:00 – 22:00",
    });

    await u.click(screen.getByRole("button", { name: "Desactivar opción: Matutino" }));
    await waitFor(() => expect(llamadas.some((l) => l.url === "/api/v1/campos/3/opciones/31")).toBe(true));
    expect(cuerpo(llamadas.find((l) => l.url === "/api/v1/campos/3/opciones/31")!.init)).toEqual({ activo: false });
  });

  it("desactiva un campo y no deja eliminar uno con valores (409)", async () => {
    const llamadas = simularApi({
      "/api/v1/campos/12": (init?: RequestInit) =>
        init?.method === "DELETE"
          ? problema(409, "CAMPO_CON_VALORES", "El campo tiene valores capturados y no se puede eliminar.")
          : json({ ...CAMPO_BONO, ...cuerpo(init) }),
      "/api/v1/campos": listadoCampos(),
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar Bono de productividad" }));
    await u.click(screen.getByRole("button", { name: "Desactivar" }));
    await waitFor(() => expect(llamadas.some((l) => l.init?.method === "PATCH")).toBe(true));
    expect(cuerpo(llamadas.find((l) => l.init?.method === "PATCH")!.init)).toEqual({ activo: false });

    await u.click(screen.getByRole("button", { name: "Eliminar campo" }));
    await u.click(screen.getByRole("button", { name: "Confirmar eliminación" }));
    expect(await screen.findByText("El campo tiene valores capturados y no se puede eliminar.")).toBeInTheDocument();
  });

  it("un campo sugerido no ofrece eliminar", async () => {
    simularApi({ "/api/v1/campos": listadoCampos() });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar Turno" }));
    expect(screen.queryByRole("button", { name: "Eliminar campo" })).not.toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("la configuración de campos no tiene violaciones críticas ni serias de axe", async () => {
    simularApi({ "/api/v1/campos": listadoCampos() });
    const { container } = montar();
    await screen.findByText("Bono de productividad");
    await esperarAccesible(container);
  });
});
