import { configure, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { RutasNotificaciones } from "../RutasNotificaciones";
import { INDICADORES, json, notificacion, simulador, type Llamada } from "../test/datos";
import { esperarAccesible } from "@/test/axe";

// Margen para equipos lentos o con la suite completa en paralelo.
configure({ asyncUtilTimeout: 8000 });

afterEach(() => vi.unstubAllGlobals());

const ENVIOS = [
  notificacion(),
  notificacion({
    id: 2,
    titulo: "Entrega de uniformes",
    modo: "CRITERIOS",
    estado: "ENVIANDO",
    audiencia_nombre: null,
    plantilla: { id: 6, nombre: "uniformes_v1", estado_meta: "APROBADA" },
    contadores: { seleccionados: 61, excluidos: 0, validos: 61, enviados: 61, entregados: 40, leidos: 10, respondieron: 0, fallidos: 0 },
    fecha_envio: "2026-11-13T15:00:00Z",
  }),
  notificacion({
    id: 4,
    titulo: "Cambio de horario nocturno",
    estado: "CON_FALLAS",
    contadores: { seleccionados: 9, excluidos: 0, validos: 9, enviados: 9, entregados: 8, leidos: 0, respondieron: 0, fallidos: 1 },
  }),
];
const PROGRAMADAS = [
  notificacion({
    id: 3,
    titulo: "Felicitación por aniversario",
    estado: "PROGRAMADA",
    modo: "CRITERIOS",
    programada_para: "2026-11-15T14:00:00Z",
    fecha_envio: null,
    contadores: { seleccionados: 18, excluidos: 0, validos: 18, enviados: 0, entregados: 0, leidos: 0, respondieron: 0, fallidos: 0 },
  }),
];
const BORRADORES = [
  notificacion({
    id: 6,
    titulo: "Bienvenida nueva planta",
    estado: "BORRADOR",
    fecha_envio: null,
    contadores: { seleccionados: 0, excluidos: 0, validos: 0, enviados: 0, entregados: 0, leidos: 0, respondieron: 0, fallidos: 0 },
  }),
];

const CONTEOS = { envios: 24, programadas: 2, borradores: 1 };

function api() {
  return simulador({
    "GET /api/v1/notificaciones/indicadores": INDICADORES,
    "GET /api/v1/notificaciones": (l: Llamada) => {
      const p = new URL(l.url, "http://localhost").searchParams.get("pestana");
      const items = p === "programadas" ? PROGRAMADAS : p === "borradores" ? BORRADORES : ENVIOS;
      return json({ items, siguiente: null, conteos: CONTEOS });
    },
  });
}

const montar = () =>
  renderizar(
    <Routes>
      <Route path="notificaciones/*" element={<RutasNotificaciones />} />
    </Routes>,
    { ruta: "/notificaciones" },
  );

describe("listado de notificaciones (cv1_08)", () => {
  it("muestra los indicadores del mes", async () => {
    api();
    montar();
    const bloque = await screen.findByRole("region", { name: "Indicadores del mes" });
    expect(await within(bloque).findByText("1,284")).toBeInTheDocument();
    expect(within(bloque).getByText("Enviadas este mes")).toBeInTheDocument();
    expect(within(bloque).getByText("96%")).toBeInTheDocument();
    expect(within(bloque).getByText("71%")).toBeInTheDocument();
    expect(within(bloque).getByText("14")).toBeInTheDocument();
    expect(within(bloque).getByText("Entregadas")).toBeInTheDocument();
    expect(within(bloque).getByText("Leídas")).toBeInTheDocument();
    expect(within(bloque).getByText("Fallidas")).toBeInTheDocument();
  });

  it("las pestañas llevan el conteo y la tabla cambia de Envíos a Programadas y Borradores", async () => {
    const llamadas = api();
    montar();
    expect(await screen.findByRole("tab", { name: "Envíos (24)" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Programadas (2)" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Borradores (1)" })).toBeInTheDocument();

    const tabla = await screen.findByRole("table", { name: "Notificaciones" });
    const filas = within(tabla).getAllByRole("row").slice(1);
    expect(filas).toHaveLength(3);
    const primera = within(filas[0]!);
    expect(primera.getByText("Aviso de cierre de nómina")).toBeInTheDocument();
    expect(primera.getByText("Todos · Grupo Industrial Norte")).toBeInTheDocument();
    expect(primera.getByText("aviso_nomina_v2")).toBeInTheDocument();
    expect(primera.getByText("118 · 6 excluidos")).toBeInTheDocument();
    expect(primera.getByText("Completado")).toBeInTheDocument();
    // 22:00 UTC del 12 de noviembre es 16:00 en la Ciudad de México.
    expect(primera.getByText("12 nov, 16:00")).toBeInTheDocument();
    expect(primera.getByRole("link", { name: "Ver detalle: Aviso de cierre de nómina" })).toHaveAttribute("href", "/notificaciones/1");
    expect(within(filas[1]!).getByText("61 de 61")).toBeInTheDocument();
    expect(within(filas[1]!).getByText("Enviando")).toBeInTheDocument();
    expect(within(filas[2]!).getByText("Con fallas")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Programadas (2)" }));
    expect(await screen.findByText("Felicitación por aniversario")).toBeInTheDocument();
    expect(screen.getByText("18 programados")).toBeInTheDocument();
    expect(screen.getByText("Programado")).toBeInTheDocument();
    expect(screen.getByText("15 nov, 08:00")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Borradores (1)" }));
    expect(await screen.findByText("Bienvenida nueva planta")).toBeInTheDocument();
    expect(screen.getByText("Sin enviar")).toBeInTheDocument();
    expect(screen.getByText("Borrador")).toBeInTheDocument();
    expect(llamadas.some((l) => l.url.includes("pestana=borradores"))).toBe(true);
  });

  it("enlaza a las plantillas de mensaje y a la nueva notificación", async () => {
    api();
    montar();
    expect(await screen.findByRole("link", { name: "Plantillas de mensaje" })).toHaveAttribute("href", "/notificaciones/plantillas");
    expect(screen.getByRole("link", { name: "+ Nueva notificación" })).toHaveAttribute("href", "/notificaciones/nueva");
  });

  it("una pestaña vacía lo dice", async () => {
    simulador({
      "GET /api/v1/notificaciones/indicadores": INDICADORES,
      "GET /api/v1/notificaciones": { items: [], siguiente: null, conteos: { envios: 0, programadas: 0, borradores: 0 } },
    });
    montar();
    expect(await screen.findByText("No hay notificaciones en esta sección.")).toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el listado de notificaciones no tiene violaciones críticas ni serias de axe", async () => {
    api();
    const { container } = montar();
    await screen.findByText("Entrega de uniformes");
    await esperarAccesible(container);
  });
});
