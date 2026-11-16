import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { RutasConstancias } from "../RutasConstancias";
import { plantilla } from "../test/datos";
import { json, problema, simulador } from "../test/simulador";
import { esperarAccesible } from "@/test/axe";

afterEach(() => vi.unstubAllGlobals());

const PLANTILLAS = [
  plantilla(),
  plantilla({ id: 8, nombre: "Constancia guardería", descripcion: "Horario de trabajo", version: 2, emitidas: 37 }),
  plantilla({ id: 9, nombre: "Constancia de ingresos", descripcion: null, version: null, estado: "BORRADOR", activa: false, emitidas: 0 }),
];

const montar = () =>
  renderizar(
    <Routes>
      <Route path="constancias/*" element={<RutasConstancias />} />
    </Routes>,
    { ruta: "/constancias" },
  );

describe("listado de plantillas (cv1_05)", () => {
  it("muestra nombre, versión, emitidas, estado y las acciones de cada plantilla", async () => {
    simulador({ "GET /api/v1/plantillas": { items: PLANTILLAS } });
    montar();
    const tabla = await screen.findByRole("table", { name: "Plantillas de constancia" });
    const filas = within(tabla).getAllByRole("row").slice(1);
    expect(filas).toHaveLength(3);

    const laboral = within(filas[0]!);
    expect(laboral.getByText("Constancia laboral")).toBeInTheDocument();
    expect(laboral.getByText("v3")).toBeInTheDocument();
    expect(laboral.getByText("142")).toBeInTheDocument();
    expect(laboral.getByText("Activa")).toBeInTheDocument();
    expect(laboral.getByRole("link", { name: "Editar Constancia laboral" })).toHaveAttribute("href", "/constancias/7");
    expect(laboral.getByRole("button", { name: "Duplicar Constancia laboral" })).toBeInTheDocument();
    expect(laboral.getByRole("button", { name: "Eliminar Constancia laboral" })).toBeInTheDocument();

    const borrador = within(filas[2]!);
    expect(borrador.getByText("Borrador")).toBeInTheDocument();
    expect(borrador.getByText("Sin publicar")).toBeInTheDocument();
    // Una plantilla sin versión publicada no se puede activar.
    expect(borrador.queryByRole("button", { name: /Activar/ })).not.toBeInTheDocument();
  });

  it("las pestañas muestran el total y llevan al historial", async () => {
    simulador({ "GET /api/v1/plantillas": { items: PLANTILLAS } });
    montar();
    expect(await screen.findByRole("link", { name: "Plantillas (3)" })).toHaveClass("activa");
    expect(screen.getByRole("link", { name: "Historial" })).toHaveAttribute("href", "/constancias/historial");
  });

  it("la fecha de actualización se muestra en la zona de México", async () => {
    simulador({ "GET /api/v1/plantillas": { items: [plantilla({ fecha_modificacion: "2026-11-13T03:30:00Z" })] } });
    montar();
    // 03:30 UTC del 13 de noviembre es el 12 de noviembre en la Ciudad de México.
    expect(await screen.findByText("12 nov 2026")).toBeInTheDocument();
  });

  it("crea una plantilla con nombre obligatorio y abre su editor", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador({
      "GET /api/v1/plantillas": { items: [] },
      "POST /api/v1/plantillas": () => json(plantilla({ id: 12, nombre: "Nueva", version: null, estado: "BORRADOR" }), 201),
      "GET /api/v1/plantillas/12": () => problema(404, "NO_ENCONTRADO", "No encontrada"),
    });
    montar();
    await usuario.click(await screen.findByRole("button", { name: "+ Nueva plantilla" }));
    const dialogo = await screen.findByRole("dialog", { name: "Nueva plantilla" });
    await usuario.click(within(dialogo).getByRole("button", { name: "Crear plantilla" }));
    expect(await within(dialogo).findByText("Escribe el nombre de la plantilla.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST")).toBe(false);

    await usuario.type(within(dialogo).getByLabelText("Nombre"), "Nueva");
    await usuario.click(within(dialogo).getByRole("button", { name: "Crear plantilla" }));
    await waitFor(() => expect(llamadas.find((l) => l.metodo === "POST")?.cuerpo).toEqual({ nombre: "Nueva", descripcion: null }));
    await waitFor(() => expect(llamadas.some((l) => l.ruta === "/api/v1/plantillas/12")).toBe(true));
  });

  it("duplica una plantilla", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador({
      "GET /api/v1/plantillas": { items: PLANTILLAS },
      "POST /api/v1/plantillas/7/duplicar": () => json(plantilla({ id: 20, nombre: "Constancia laboral (copia)" }), 201),
      "GET /api/v1/plantillas/20": () => problema(404, "NO_ENCONTRADO", "No encontrada"),
    });
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Duplicar Constancia laboral" }));
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "POST" && l.ruta === "/api/v1/plantillas/7/duplicar")).toBe(true));
  });

  it("elimina solo tras confirmar", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador({
      "GET /api/v1/plantillas": { items: PLANTILLAS },
      "DELETE /api/v1/plantillas/8": () => new Response(null, { status: 204 }),
    });
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Eliminar Constancia guardería" }));
    const dialogo = await screen.findByRole("dialog", { name: "Eliminar plantilla" });
    expect(llamadas.some((l) => l.metodo === "DELETE")).toBe(false);
    await usuario.click(within(dialogo).getByRole("button", { name: "Sí, eliminar" }));
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "DELETE" && l.ruta === "/api/v1/plantillas/8")).toBe(true));
    expect(await screen.findByText("Plantilla eliminada.")).toBeInTheDocument();
  });

  it("una plantilla sin versión publicada informa el 409 al activarla", async () => {
    const usuario = userEvent.setup();
    simulador({
      "GET /api/v1/plantillas": { items: [plantilla({ id: 10, nombre: "Inactiva", estado: "INACTIVA", activa: false })] },
      "PATCH /api/v1/plantillas/10": () => problema(409, "PLANTILLA_SIN_VERSION", "Publica una versión antes de activar la plantilla."),
    });
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Activar Inactiva" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Publica una versión antes de activar la plantilla.");
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el listado de plantillas no tiene violaciones críticas ni serias de axe", async () => {
    simulador({ "GET /api/v1/plantillas": { items: PLANTILLAS } });
    const { container } = montar();
    await screen.findByRole("table", { name: "Plantillas de constancia" });
    await esperarAccesible(container);
  });
});
