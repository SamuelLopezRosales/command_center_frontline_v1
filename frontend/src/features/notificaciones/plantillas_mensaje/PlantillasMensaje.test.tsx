import { configure, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { RutasNotificaciones } from "../RutasNotificaciones";
import { json, plantillaMensaje, problema, simulador, type Llamada } from "../test/datos";
import { esperarAccesible } from "@/test/axe";

// Las pruebas con muchos pasos de usuario tardan más que el límite por defecto.
vi.setConfig({ testTimeout: 20000 });
configure({ asyncUtilTimeout: 8000 });

afterEach(() => vi.unstubAllGlobals());

const PLANTILLAS = [
  plantillaMensaje(),
  plantillaMensaje({ id: 6, nombre: "aviso_nomina_v2", estado_meta: "EN_REVISION", cantidad_variables: 1 }),
  plantillaMensaje({
    id: 7,
    nombre: "bienvenida_v1",
    estado_meta: "RECHAZADA",
    motivo_rechazo: "El texto contiene una promoción no permitida en la categoría Utilidad.",
  }),
  plantillaMensaje({ id: 8, nombre: "borrador_nuevo", estado_meta: "BORRADOR", categoria: "MARKETING" }),
];

const montar = () =>
  renderizar(
    <Routes>
      <Route path="notificaciones/*" element={<RutasNotificaciones />} />
    </Routes>,
    { ruta: "/notificaciones/plantillas" },
  );

const fila = async (nombre: string) => {
  const tabla = await screen.findByRole("table", { name: "Plantillas de mensaje" });
  const f = within(tabla)
    .getAllByRole("row")
    .find((r) => within(r).queryByText(nombre));
  if (!f) throw new Error(`Sin fila para ${nombre}`);
  return within(f);
};

describe("catálogo de plantillas de mensaje (cv1_08)", () => {
  it("muestra el estado de Meta de cada plantilla y el motivo de rechazo", async () => {
    simulador({ "GET /api/v1/plantillas-mensaje": { items: PLANTILLAS, siguiente: null } });
    montar();
    const aprobada = await fila("recordatorio_uniformes_v1");
    expect(aprobada.getByText("Aprobada")).toBeInTheDocument();
    expect(aprobada.getByText("2 variables")).toBeInTheDocument();
    expect(aprobada.getByText("Utilidad")).toBeInTheDocument();
    // Una plantilla aprobada ya no se envía a revisión.
    expect(aprobada.queryByRole("button", { name: /Enviar a revisión/ })).not.toBeInTheDocument();

    const revision = await fila("aviso_nomina_v2");
    expect(revision.getByText("En revisión")).toBeInTheDocument();
    expect(revision.getByRole("button", { name: "Sincronizar estado aviso_nomina_v2" })).toBeInTheDocument();

    const rechazada = await fila("bienvenida_v1");
    expect(rechazada.getByText("Rechazada")).toBeInTheDocument();
    expect(rechazada.getByText(/Motivo de rechazo:/)).toBeInTheDocument();
    expect(rechazada.getByText(/promoción no permitida/)).toBeInTheDocument();
    expect(rechazada.getByRole("button", { name: "Enviar a revisión bienvenida_v1" })).toBeInTheDocument();

    const borrador = await fila("borrador_nuevo");
    expect(borrador.getByText("Borrador")).toBeInTheDocument();
    expect(borrador.getByText("Marketing")).toBeInTheDocument();
  });

  it("envía a revisión una plantilla en borrador y refresca el catálogo", async () => {
    let revisada = false;
    const llamadas = simulador({
      "GET /api/v1/plantillas-mensaje": () =>
        json({ items: PLANTILLAS.map((p) => (p.id === 8 && revisada ? { ...p, estado_meta: "EN_REVISION" } : p)), siguiente: null }),
      "POST /api/v1/plantillas-mensaje/8/enviar-revision": () => {
        revisada = true;
        return json({ ...PLANTILLAS[3], estado_meta: "EN_REVISION" }, 202);
      },
    });
    montar();
    const borrador = await fila("borrador_nuevo");
    await userEvent.click(borrador.getByRole("button", { name: "Enviar a revisión borrador_nuevo" }));
    expect(await screen.findByText("Plantilla enviada a revisión de Meta.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST" && l.ruta.endsWith("/8/enviar-revision"))).toBe(true);
    await waitFor(async () => expect((await fila("borrador_nuevo")).getByText("En revisión")).toBeInTheDocument());
  });

  it("duplica una plantilla como borrador", async () => {
    const llamadas = simulador({
      "GET /api/v1/plantillas-mensaje": { items: PLANTILLAS, siguiente: null },
      "POST /api/v1/plantillas-mensaje/7/duplicar": () => json(plantillaMensaje({ id: 9, nombre: "bienvenida_v1_copia", estado_meta: "BORRADOR" }), 201),
    });
    montar();
    const rechazada = await fila("bienvenida_v1");
    await userEvent.click(rechazada.getByRole("button", { name: "Duplicar bienvenida_v1" }));
    expect(await screen.findByText("Plantilla duplicada como borrador.")).toBeInTheDocument();
    expect(llamadas.filter((l) => l.metodo === "POST" && l.ruta.endsWith("/7/duplicar"))).toHaveLength(1);
  });

  it("muestra el error de Meta al enviar a revisión", async () => {
    simulador({
      "GET /api/v1/plantillas-mensaje": { items: PLANTILLAS, siguiente: null },
      "POST /api/v1/plantillas-mensaje/8/enviar-revision": () =>
        problema(502, "ERROR_PROVEEDOR_META", "No se pudo contactar a Meta."),
    });
    montar();
    const borrador = await fila("borrador_nuevo");
    await userEvent.click(borrador.getByRole("button", { name: "Enviar a revisión borrador_nuevo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Meta no respondió. Intenta de nuevo en unos minutos.");
  });

  it("crea una plantilla con errores por campo del servidor", async () => {
    const llamadas = simulador({
      "GET /api/v1/plantillas-mensaje": { items: [], siguiente: null },
      "POST /api/v1/plantillas-mensaje": (l: Llamada) => {
        const c = l.cuerpo as { nombre: string };
        if (c.nombre === "duplicada") {
          return problema(409, "NOMBRE_DUPLICADO", "Ya existe", [{ campo: "nombre", codigo: "NOMBRE_DUPLICADO", mensaje: "Ya existe una plantilla con ese nombre." }]);
        }
        return json(plantillaMensaje({ id: 10, nombre: c.nombre, estado_meta: "BORRADOR" }), 201);
      },
    });
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "+ Nueva plantilla" }));
    const dialogo = screen.getByRole("dialog", { name: "Nueva plantilla de mensaje" });

    // Validación local: el nombre solo admite minúsculas y guiones bajos.
    await userEvent.type(within(dialogo).getByLabelText(/Nombre/), "Aviso Nómina");
    await userEvent.type(within(dialogo).getByLabelText(/Texto con variables/), "Hola {{{{1}}");
    await userEvent.click(within(dialogo).getByRole("button", { name: "Crear plantilla" }));
    expect(await within(dialogo).findByText("Usa solo minúsculas, números y guiones bajos.")).toBeInTheDocument();
    expect(llamadas.filter((l) => l.metodo === "POST")).toHaveLength(0);

    // Error del servidor aplicado al campo.
    await userEvent.clear(within(dialogo).getByLabelText(/Nombre/));
    await userEvent.type(within(dialogo).getByLabelText(/Nombre/), "duplicada");
    await userEvent.click(within(dialogo).getByRole("button", { name: "Crear plantilla" }));
    expect(await within(dialogo).findByText("Ya existe una plantilla con ese nombre.")).toBeInTheDocument();

    await userEvent.clear(within(dialogo).getByLabelText(/Nombre/));
    await userEvent.type(within(dialogo).getByLabelText(/Nombre/), "aviso_nuevo");
    await userEvent.click(within(dialogo).getByRole("button", { name: "Crear plantilla" }));
    expect(await screen.findByText("Plantilla creada como borrador.")).toBeInTheDocument();
    const envio = llamadas.filter((l) => l.metodo === "POST").at(-1)!;
    expect(envio.cuerpo).toEqual({ nombre: "aviso_nuevo", categoria: "UTILITY", idioma: "es_MX", texto_con_variables: "Hola {{1}}", ejemplos: [] });
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el catálogo de plantillas de mensaje no tiene violaciones críticas ni serias de axe", async () => {
    simulador({ "GET /api/v1/plantillas-mensaje": { items: PLANTILLAS, siguiente: null } });
    const { container } = montar();
    await fila("recordatorio_uniformes_v1");
    await esperarAccesible(container);
  });
});
