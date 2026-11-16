import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { RutasConstancias } from "../RutasConstancias";
import { plantilla } from "../test/datos";
import { json, problema, simulador } from "../test/simulador";
import type { ItemHistorial } from "./tipos";
import { esperarAccesible } from "@/test/axe";

afterEach(() => vi.unstubAllGlobals());

const item = (sobre: Partial<ItemHistorial>): ItemHistorial => ({
  id: 1,
  folio: "CG-2026-0001",
  colaborador_nombre: "Ana Ramírez",
  plantilla_nombre: "Constancia laboral",
  version: 3,
  fecha: "2026-11-13T15:42:00Z",
  canal: "WHATSAPP",
  estado_entrega: "ENTREGADA",
  ...sobre,
});

const ITEMS = [
  item({ id: 142, folio: "CG-2026-0142", estado_entrega: "ENTREGADA" }),
  item({ id: 140, folio: "CG-2026-0140", colaborador_nombre: "Miguel Herrera", estado_entrega: "FALLIDA", version: 4 }),
  item({ id: 136, folio: "CG-2026-0136", colaborador_nombre: "Ricardo Salinas", estado_entrega: "PENDIENTE", version: 2 }),
];

const pagina = (items: ItemHistorial[], siguiente: string | null = null) => ({ items, siguiente });

const montar = () =>
  renderizar(
    <Routes>
      <Route path="constancias/*" element={<RutasConstancias />} />
    </Routes>,
    { ruta: "/constancias/historial" },
  );

const baseApi = (extra: Record<string, unknown> = {}) => ({
  "GET /api/v1/plantillas": { items: [plantilla(), plantilla({ id: 8, nombre: "Constancia guardería" })] },
  "GET /api/v1/constancias/historial": pagina(ITEMS),
  ...extra,
});

const fila = (folio: string) => within(screen.getByText(folio).closest("tr")!);

describe("historial de constancias (cv1_07)", () => {
  it("muestra folio, colaborador, plantilla, versión, fecha, canal y estado", async () => {
    simulador(baseApi());
    montar();
    const tabla = await screen.findByRole("table", { name: "Historial de constancias" });
    const f = within(tabla);
    expect(f.getByText("CG-2026-0142")).toBeInTheDocument();
    const fallida = fila("CG-2026-0140");
    expect(fallida.getByText("Miguel Herrera")).toBeInTheDocument();
    expect(fallida.getByText("v4")).toBeInTheDocument();
    expect(fallida.getByText("WhatsApp")).toBeInTheDocument();
    expect(fallida.getByText("Fallida")).toBeInTheDocument();
    // 15:42 UTC es 09:42 en la Ciudad de México.
    expect(fila("CG-2026-0142").getByText("13 nov, 09:42")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 3 constancias")).toBeInTheDocument();
  });

  it("descarga solo con ENTREGADA o FALLIDA y reenvío solo con FALLIDA; PENDIENTE no ofrece descarga", async () => {
    simulador(baseApi());
    montar();
    await screen.findByText("CG-2026-0142");
    const entregada = fila("CG-2026-0142");
    expect(entregada.getByRole("button", { name: "Descargar CG-2026-0142" })).toBeInTheDocument();
    expect(entregada.queryByRole("button", { name: /Reenviar/ })).not.toBeInTheDocument();

    const fallida = fila("CG-2026-0140");
    expect(fallida.getByRole("button", { name: "Reenviar CG-2026-0140" })).toBeInTheDocument();
    expect(fallida.getByRole("button", { name: "Descargar CG-2026-0140" })).toBeInTheDocument();

    const pendiente = fila("CG-2026-0136");
    expect(pendiente.queryByRole("button", { name: /Descargar/ })).not.toBeInTheDocument();
    expect(pendiente.queryByRole("button", { name: /Reenviar/ })).not.toBeInTheDocument();
  });

  it("descargar pide la URL firmada y la abre en otra pestaña", async () => {
    const usuario = userEvent.setup();
    const abrir = vi.fn();
    vi.stubGlobal("open", abrir);
    const llamadas = simulador(
      baseApi({ "POST /api/v1/constancias/142/descarga": { url: "https://cdn.example.com/c.pdf?firma=x", expira: "2026-11-14T15:42:00Z" } }),
    );
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Descargar CG-2026-0142" }));
    await waitFor(() => expect(abrir).toHaveBeenCalledWith("https://cdn.example.com/c.pdf?firma=x", "_blank", "noopener,noreferrer"));
    expect(llamadas.some((l) => l.metodo === "POST" && l.ruta === "/api/v1/constancias/142/descarga")).toBe(true);
  });

  it("reenviar una constancia FALLIDA llama a la API (202 sin cuerpo) y lo confirma", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(baseApi({ "POST /api/v1/constancias/140/reenviar": () => new Response(null, { status: 202 }) }));
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Reenviar CG-2026-0140" }));
    expect(await screen.findByText("Se programó el reenvío de la constancia CG-2026-0140.")).toBeInTheDocument();
    expect(llamadas.filter((l) => l.metodo === "POST" && l.ruta === "/api/v1/constancias/140/reenviar")).toHaveLength(1);
  });

  it("muestra el error de la API si no se puede reenviar", async () => {
    const usuario = userEvent.setup();
    simulador(
      baseApi({ "POST /api/v1/constancias/140/reenviar": () => problema(409, "CONSTANCIA_NO_FALLIDA", "Solo se puede reenviar una constancia con entrega fallida.") }),
    );
    montar();
    await usuario.click(await screen.findByRole("button", { name: "Reenviar CG-2026-0140" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Solo se puede reenviar una constancia con entrega fallida.");
  });

  it("los filtros se envían al API: texto, fechas, plantilla y estado", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(baseApi());
    montar();
    await screen.findByText("CG-2026-0142");
    const ultima = () => new URL(llamadas.filter((l) => l.ruta === "/api/v1/constancias/historial").at(-1)!.url, "http://x").searchParams;

    await usuario.selectOptions(screen.getByRole("combobox", { name: "Estado" }), "FALLIDA");
    await waitFor(() => expect(ultima().get("estado")).toBe("FALLIDA"));

    await usuario.selectOptions(screen.getByRole("combobox", { name: "Plantilla" }), "8");
    await waitFor(() => expect(ultima().get("plantilla_id")).toBe("8"));

    await usuario.type(screen.getByLabelText("Desde"), "2026-11-01");
    await waitFor(() => expect(ultima().get("desde")).toBe("2026-11-01"));
    await usuario.type(screen.getByLabelText("Hasta"), "2026-11-13");
    await waitFor(() => expect(ultima().get("hasta")).toBe("2026-11-13"));

    await usuario.type(screen.getByRole("searchbox", { name: "Buscar colaborador o folio" }), "CG-2026");
    await waitFor(() => expect(ultima().get("q")).toBe("CG-2026"), { timeout: 2000 });
    // Todos los filtros siguen aplicados juntos.
    expect(ultima().get("estado")).toBe("FALLIDA");
    expect(ultima().get("plantilla_id")).toBe("8");
    expect(ultima().get("cursor")).toBeNull();
  });

  it("pagina con Anterior y Siguiente", async () => {
    const usuario = userEvent.setup();
    const llamadas = simulador(
      baseApi({
        "GET /api/v1/constancias/historial": (l: { url: string }) => {
          const c = new URL(l.url, "http://x").searchParams.get("cursor");
          return json(c === null ? pagina(ITEMS, "cursor-2") : pagina([item({ id: 9, folio: "CG-2026-0009" })]));
        },
      }),
    );
    montar();
    await screen.findByText("CG-2026-0142");
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    await usuario.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("CG-2026-0009")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 1 constancia")).toBeInTheDocument();
    expect(new URL(llamadas.filter((l) => l.ruta.endsWith("/historial")).at(-1)!.url, "http://x").searchParams.get("cursor")).toBe("cursor-2");
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
    await usuario.click(screen.getByRole("button", { name: "Anterior" }));
    expect(await screen.findByText("CG-2026-0142")).toBeInTheDocument();
  });

  it("aplica los filtros que llegan en la URL (enlaces del dashboard)", async () => {
    const llamadas = simulador(baseApi());
    renderizar(
      <Routes>
        <Route path="constancias/*" element={<RutasConstancias />} />
      </Routes>,
      { ruta: "/constancias/historial?estado=FALLIDA&q=CG-2026-0140" },
    );
    await screen.findByText("CG-2026-0142");
    const url = new URL(llamadas.filter((l) => l.ruta.endsWith("/historial")).at(-1)!.url, "http://x");
    expect(url.searchParams.get("estado")).toBe("FALLIDA");
    await waitFor(() => expect(screen.getByRole("searchbox", { name: "Buscar colaborador o folio" })).toHaveValue("CG-2026-0140"));
  });

  it("sin resultados muestra el mensaje vacío", async () => {
    simulador(baseApi({ "GET /api/v1/constancias/historial": pagina([]) }));
    montar();
    expect(await screen.findByText("No hay constancias con esos filtros.")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 0 constancias")).toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el historial no tiene violaciones críticas ni serias de axe", async () => {
    simulador(baseApi());
    const { container } = montar();
    await screen.findByRole("table", { name: "Historial de constancias" });
    await esperarAccesible(container);
  });
});

describe("fechas en la zona de México (CC-NFR-014)", () => {
  it("una hora UTC de madrugada cae en el día anterior de la Ciudad de México", async () => {
    simulador(baseApi({ "GET /api/v1/constancias/historial": pagina([item({ id: 150, folio: "CG-2026-0150", fecha: "2026-11-14T03:30:00Z" })]) }));
    montar();
    await screen.findByRole("table", { name: "Historial de constancias" });
    expect(fila("CG-2026-0150").getByText("13 nov, 21:30")).toBeInTheDocument();
  });
});
