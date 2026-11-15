import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { DINAMICOS, ORGS, PLANTAS, fila, json, listadoCampos, simularRutas, type Llamada } from "@/test/fixturas220";
import { RutasColaboradores } from "./RutasColaboradores";

afterEach(() => vi.unstubAllGlobals());

const TOTAL = 25;

function api(total = TOTAL) {
  return simularRutas((url) => {
    if (url.pathname === "/api/v1/organizaciones") return json({ items: ORGS });
    if (url.pathname === "/api/v1/plantas") return json({ items: PLANTAS });
    if (url.pathname === "/api/v1/campos") return json(listadoCampos(DINAMICOS));
    if (url.pathname === "/api/v1/colaboradores") {
      const pagina = Number(url.searchParams.get("pagina") ?? 1);
      const limite = Number(url.searchParams.get("limite") ?? 10);
      const desde = (pagina - 1) * limite;
      const cuantas = Math.max(0, Math.min(limite, total - desde));
      const area = url.searchParams.getAll("columnas").includes("CAMP-0001");
      const items = Array.from({ length: cuantas }, (_, i) => fila(desde + i + 1, area ? { campos: { "CAMP-0001": "ALMACEN" } } : {}));
      return json({ items, pagina, limite, total });
    }
    return undefined;
  });
}

const montar = () =>
  renderizar(
    <Routes>
      <Route path="colaboradores/*" element={<RutasColaboradores />} />
    </Routes>,
    { ruta: "/colaboradores" },
  );

const listados = (llamadas: Llamada[]) => llamadas.filter((l) => l.url.startsWith("/api/v1/colaboradores?"));
const ultimo = (llamadas: Llamada[]) => new URLSearchParams(listados(llamadas).at(-1)!.url.split("?")[1]);

describe("listado de colaboradores (cv1_02)", () => {
  it("muestra la tabla con las columnas por defecto, el total y el estatus ACTIVO preseleccionado", async () => {
    const llamadas = api();
    montar();
    expect(await screen.findByText("Colaborador Número 1")).toBeInTheDocument();
    for (const h of ["Nº empleado", "Nombre", "Organización", "Planta", "Puesto", "Tipo", "Estatus", "Acción"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
    expect(screen.getByText("EMP-0001")).toBeInTheDocument();
    expect(screen.getAllByText("Administrativo").length).toBeGreaterThan(0);
    expect(screen.getByText("25 colaboradores")).toBeInTheDocument();
    expect(screen.getByLabelText("Estatus")).toHaveValue("ACTIVO");
    expect(ultimo(llamadas).get("estatus")).toBe("ACTIVO");
    expect(screen.getAllByRole("link", { name: /^Abrir/ })[0]).toHaveAttribute("href", "/colaboradores/1");
  });

  it("enlaza a configuración de campos, carga masiva, organizaciones y alta", async () => {
    api();
    montar();
    expect(await screen.findByRole("link", { name: "Configurar campos" })).toHaveAttribute("href", "/campos");
    expect(screen.getByRole("link", { name: "Carga masiva" })).toHaveAttribute("href", "/cargas");
    expect(screen.getByRole("link", { name: "Organizaciones y plantas" })).toHaveAttribute("href", "/organizaciones");
    expect(screen.getByRole("link", { name: "+ Nuevo colaborador" })).toHaveAttribute("href", "/colaboradores/nuevo");
  });

  it("buscador por nombre o número de empleado (con retraso) y vuelve a la página 1", async () => {
    const llamadas = api();
    const u = userEvent.setup();
    montar();
    await screen.findByText("Colaborador Número 1");
    await u.type(screen.getByLabelText("Buscar por nombre o número de empleado"), "Ricardo");
    await waitFor(() => expect(ultimo(llamadas).get("q")).toBe("Ricardo"));
    expect(ultimo(llamadas).get("pagina")).toBe("1");
  });

  it("filtros por organización, planta, estatus y tipo de empleado", async () => {
    const llamadas = api();
    const u = userEvent.setup();
    montar();
    await screen.findByText("Colaborador Número 1");
    // Las opciones llegan del catálogo.
    await screen.findByRole("option", { name: "ORG02 · Servicios del Norte" });

    await u.selectOptions(screen.getByLabelText("Organización"), "2");
    await waitFor(() => expect(ultimo(llamadas).get("organizacion_id")).toBe("2"));
    await u.selectOptions(screen.getByLabelText("Planta"), "Monterrey");
    await waitFor(() => expect(ultimo(llamadas).get("planta_id")).toBe("2"));
    await u.selectOptions(screen.getByLabelText("Tipo de empleado"), "OPERATIVO");
    await waitFor(() => expect(ultimo(llamadas).get("tipo_empleado")).toBe("OPERATIVO"));
    await u.selectOptions(screen.getByLabelText("Estatus"), "BAJA");
    await waitFor(() => expect(ultimo(llamadas).get("estatus")).toBe("BAJA"));
    await u.selectOptions(screen.getByLabelText("Estatus"), "");
    await waitFor(() => expect(ultimo(llamadas).has("estatus")).toBe(false));
    // Los valores sensibles (celular, NSS…) nunca viajan en la URL.
    expect(llamadas.every((l) => !/celular=|nss|rfc/i.test(l.url))).toBe(true);
  });

  it("selector de columnas: agrega un campo dinámico, lo pide a la API y no ofrece sensibles", async () => {
    const llamadas = api();
    const u = userEvent.setup();
    montar();
    await screen.findByText("Colaborador Número 1");
    // 10 columnas fijas + Área y Turno (activos y no sensibles).
    const boton = await screen.findByRole("button", { name: "Columnas (7 de 12)" });
    await u.click(boton);
    const grupo = screen.getByRole("group", { name: "Columnas visibles" });
    expect(within(grupo).queryByLabelText("Sueldo (MXN)")).not.toBeInTheDocument();
    expect(within(grupo).queryByLabelText("NSS")).not.toBeInTheDocument();
    expect(within(grupo).queryByLabelText("Ruta de transporte")).not.toBeInTheDocument();

    await u.click(within(grupo).getByLabelText("Área"));
    await waitFor(() => expect(ultimo(llamadas).getAll("columnas")).toEqual(["CAMP-0001"]));
    expect(await screen.findByRole("columnheader", { name: "Área" })).toBeInTheDocument();
    expect((await screen.findAllByText("Almacén")).length).toBe(10);
    expect(screen.getByRole("button", { name: "Columnas (8 de 12)" })).toBeInTheDocument();

    await u.click(within(grupo).getByLabelText("Puesto"));
    expect(screen.queryByRole("columnheader", { name: "Puesto" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Columnas (7 de 12)" })).toBeInTheDocument();
  });

  it("paginación: Anterior y Siguiente con el rango mostrado", async () => {
    const llamadas = api();
    const u = userEvent.setup();
    montar();
    expect(await screen.findByText("Mostrando 1–10 de 25 colaboradores")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();

    await u.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("Mostrando 11–20 de 25 colaboradores")).toBeInTheDocument();
    expect(ultimo(llamadas).get("pagina")).toBe("2");
    expect(await screen.findByText("Colaborador Número 11")).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("Mostrando 21–25 de 25 colaboradores")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();

    await u.click(screen.getByRole("button", { name: "Anterior" }));
    expect(await screen.findByText("Mostrando 11–20 de 25 colaboradores")).toBeInTheDocument();
  });

  it("sin resultados muestra un mensaje", async () => {
    api(0);
    montar();
    expect(await screen.findByText("No hay colaboradores con estos filtros.")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 0–0 de 0 colaboradores")).toBeInTheDocument();
  });
});
