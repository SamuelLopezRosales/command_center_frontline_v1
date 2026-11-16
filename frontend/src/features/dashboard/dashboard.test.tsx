import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "./Dashboard";
import { USUARIO_PRUEBA, authSimulado, renderizar, simularApi } from "@/test/ayudantes";
import type { Alerta, ItemConstancia, ItemSolicitud, ResumenDashboard } from "./tipos";
import { esperarAccesible } from "@/test/axe";

afterEach(() => vi.unstubAllGlobals());

const resumen: ResumenDashboard = { colaboradores_activos: 118, constancias_mes: 37, solicitudes_en_proceso: 2, plantillas_activas: 3, vacio: false };
const solicitudes: ItemSolicitud[] = [
  { id: 1, colaborador_nombre: "Samuel López Rosales", plantilla_nombre: "Constancia laboral", version: 3, estado: "EN_PROCESO" },
  { id: 2, colaborador_nombre: "Ana Lucía Ramírez Torres", plantilla_nombre: "Constancia guardería", version: 2, estado: "ENTREGADA" },
  { id: 3, colaborador_nombre: "Miguel Ángel Herrera Cruz", plantilla_nombre: "Constancia consulado", version: 4, estado: "FALLIDA" },
];
const constancias: ItemConstancia[] = [
  {
    id: 142,
    folio: "CG-2026-0142",
    colaborador_nombre: "Samuel López Rosales",
    plantilla_nombre: "Constancia laboral",
    version: 3,
    fecha: "2026-11-13T15:42:00Z",
    estado_entrega: "ENTREGADA",
  },
  {
    id: 140,
    folio: "CG-2026-0140",
    colaborador_nombre: "Miguel Ángel Herrera Cruz",
    plantilla_nombre: "Constancia consulado",
    version: 4,
    fecha: "2026-11-12T23:30:00Z",
    estado_entrega: "FALLIDA",
  },
];
const alertas: Alerta[] = [
  {
    tipo: "SIN_CONSENTIMIENTO",
    titulo: "3 colaboradores sin consentimiento de WhatsApp",
    detalle: "Ricardo Salinas Ibarra, Valeria Núñez Ortega y 1 más",
    total: 3,
    enlace: "/colaboradores",
  },
  { tipo: "CONSTANCIA_FALLIDA", titulo: "Constancia consulado fallida", detalle: "Miguel Ángel Herrera Cruz", total: 1, enlace: "/constancias" },
];

const sesion = () => authSimulado({ haySesion: async () => true });
const montar = () => renderizar(<Dashboard />, { auth: sesion() });

describe("dashboard (cv1_01)", () => {
  it("muestra las cuatro tarjetas con las cifras del resumen", async () => {
    simularApi({
      "/api/v1/usuarios/yo": USUARIO_PRUEBA,
      "/api/v1/sesion/iniciar": undefined,
      "/api/v1/dashboard/resumen": resumen,
      "/api/v1/dashboard/solicitudes-recientes": [],
      "/api/v1/dashboard/constancias-recientes": [],
      "/api/v1/dashboard/alertas": [],
    });
    montar();
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    const activos = await screen.findByTestId("tarjeta-activos");
    expect(await within(activos).findByText("118")).toBeInTheDocument();
    expect(within(activos).getByText("Activos")).toBeInTheDocument();
    expect(within(screen.getByTestId("tarjeta-mes")).getByText("37")).toBeInTheDocument();
    expect(within(screen.getByTestId("tarjeta-mes")).getByText("Constancias este mes")).toBeInTheDocument();
    expect(within(screen.getByTestId("tarjeta-proceso")).getByText("2")).toBeInTheDocument();
    expect(within(screen.getByTestId("tarjeta-plantillas")).getByText("3")).toBeInTheDocument();
    expect(await screen.findByText("Bienvenido, David Bet")).toBeInTheDocument();
  });

  it("lista solicitudes recientes, constancias recientes y alertas con su enlace", async () => {
    simularApi({
      "/api/v1/usuarios/yo": USUARIO_PRUEBA,
      "/api/v1/sesion/iniciar": undefined,
      "/api/v1/dashboard/resumen": resumen,
      "/api/v1/dashboard/solicitudes-recientes": solicitudes,
      "/api/v1/dashboard/constancias-recientes": constancias,
      "/api/v1/dashboard/alertas": alertas,
    });
    montar();

    const seccionSol = (await screen.findByRole("heading", { name: "Solicitudes recientes" })).closest("section")!;
    expect(await within(seccionSol).findByText("Samuel López Rosales")).toBeInTheDocument();
    expect(within(seccionSol).getByText("Constancia laboral · v3")).toBeInTheDocument();
    expect(within(seccionSol).getByText("EN PROCESO")).toHaveClass("proceso");
    expect(within(seccionSol).getByText("ENTREGADA")).toHaveClass("ok");
    expect(within(seccionSol).getByText("FALLIDA")).toHaveClass("error");

    const seccionCon = (await screen.findByRole("heading", { name: "Constancias recientes" })).closest("section")!;
    expect(await within(seccionCon).findByText("CG-2026-0142")).toBeInTheDocument();
    expect(within(seccionCon).getByText("Constancia laboral v3")).toBeInTheDocument();
    // 15:42 UTC = 09:42 en la Ciudad de México.
    expect(within(seccionCon).getByText(/09:42/)).toBeInTheDocument();
    expect(within(seccionCon).getAllByRole("link", { name: /Descargar/ })).toHaveLength(2);

    const seccionAle = (await screen.findByRole("heading", { name: "Alertas" })).closest("section")!;
    expect(await within(seccionAle).findByText("3 colaboradores sin consentimiento de WhatsApp")).toBeInTheDocument();
    expect(within(seccionAle).getByText("Miguel Ángel Herrera Cruz")).toBeInTheDocument();
    const enlace = within(seccionAle).getByRole("link", { name: /Revisar: Constancia consulado fallida/ });
    expect(enlace).toHaveAttribute("href", "/constancias");
  });

  it("estado sin datos: muestra el mensaje y no oculta las tarjetas", async () => {
    simularApi({
      "/api/v1/usuarios/yo": USUARIO_PRUEBA,
      "/api/v1/sesion/iniciar": undefined,
      "/api/v1/dashboard/resumen": { colaboradores_activos: 0, constancias_mes: 0, solicitudes_en_proceso: 0, plantillas_activas: 0, vacio: true },
      "/api/v1/dashboard/solicitudes-recientes": [],
      "/api/v1/dashboard/constancias-recientes": [],
      "/api/v1/dashboard/alertas": [],
    });
    montar();
    expect(await screen.findByText(/Aún no hay datos para mostrar/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dar de alta colaboradores" })).toHaveAttribute("href", "/colaboradores");
    expect(await screen.findByText("No hay solicitudes recientes.")).toBeInTheDocument();
    expect(screen.getByText("No hay constancias recientes.")).toBeInTheDocument();
    expect(screen.getByText("No hay alertas pendientes.")).toBeInTheDocument();
    expect(within(screen.getByTestId("tarjeta-activos")).getByText("0")).toBeInTheDocument();
  });

  it("si una sección falla, muestra el error y deja reintentar sin romper el resto", async () => {
    simularApi({
      "/api/v1/usuarios/yo": USUARIO_PRUEBA,
      "/api/v1/sesion/iniciar": undefined,
      "/api/v1/dashboard/resumen": resumen,
      "/api/v1/dashboard/solicitudes-recientes": solicitudes,
      "/api/v1/dashboard/constancias-recientes": constancias,
      "/api/v1/dashboard/alertas": () => new Response(JSON.stringify({ title: "Error", status: 500, codigo: "ERROR" }), { status: 500 }),
    });
    montar();
    expect((await screen.findAllByText("Samuel López Rosales")).length).toBeGreaterThan(0);
    const seccionAle = (await screen.findByRole("heading", { name: "Alertas" })).closest("section")!;
    expect(await within(seccionAle).findByRole("alert")).toHaveTextContent("No se pudo cargar esta sección.");
    expect(within(seccionAle).getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el dashboard con datos no tiene violaciones críticas ni serias de axe", async () => {
    simularApi({
      "/api/v1/usuarios/yo": USUARIO_PRUEBA,
      "/api/v1/sesion/iniciar": undefined,
      "/api/v1/dashboard/resumen": resumen,
      "/api/v1/dashboard/solicitudes-recientes": solicitudes,
      "/api/v1/dashboard/constancias-recientes": constancias,
      "/api/v1/dashboard/alertas": alertas,
    });
    const { container } = montar();
    await screen.findByText("CG-2026-0142");
    await screen.findByText("3 colaboradores sin consentimiento de WhatsApp");
    await esperarAccesible(container);
  });
});

describe("fechas en la zona de México (CC-NFR-014)", () => {
  it("una hora UTC de madrugada cae en el día anterior de la Ciudad de México", async () => {
    simularApi({
      "/api/v1/usuarios/yo": USUARIO_PRUEBA,
      "/api/v1/sesion/iniciar": undefined,
      "/api/v1/dashboard/resumen": resumen,
      "/api/v1/dashboard/solicitudes-recientes": [],
      "/api/v1/dashboard/constancias-recientes": [{ ...constancias[0]!, fecha: "2026-11-14T03:30:00Z" }],
      "/api/v1/dashboard/alertas": [],
    });
    montar();
    // 03:30 UTC del 14 de noviembre son las 21:30 del 13 de noviembre en México (UTC-6).
    const texto = await screen.findByText(/21:30/);
    expect(texto.textContent).toMatch(/13/);
    expect(texto.textContent).not.toMatch(/03:30/);
  });
});
