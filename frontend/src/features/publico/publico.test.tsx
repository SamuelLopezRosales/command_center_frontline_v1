import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rutas } from "@/app/rutas";
import { json, problema, simulador } from "@/features/constancias/test/simulador";
import { renderizar } from "@/test/ayudantes";

afterEach(() => vi.unstubAllGlobals());

const CODIGO = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA";
const TOKEN = "tok_AbCdEfGhIjKlMnOpQrStUv"; // pragma: allowlist secret

describe("verificación pública /v/:codigo", () => {
  it("sin sesión muestra nombre, folio, fecha y estado, sin enviar credenciales", async () => {
    const llamadas = simulador({
      [`GET /api/v1/publico/verificar/${CODIGO}`]: { nombre: "Samuel López Rosales", folio: "CG-2026-0142", fecha_emision: "2026-11-13T15:42:00Z", estado: "VIGENTE" },
    });
    renderizar(<Rutas />, { ruta: `/v/${CODIGO}` });

    expect(await screen.findByRole("heading", { name: "Verificación de constancia" })).toBeInTheDocument();
    expect(await screen.findByText("Samuel López Rosales")).toBeInTheDocument();
    expect(screen.getByText("CG-2026-0142")).toBeInTheDocument();
    expect(screen.getByText("13/11/2026")).toBeInTheDocument();
    expect(screen.getByText("Vigente")).toHaveClass("ok");
    // No se pide la sesión: sin pantalla de acceso, sin Authorization y sin llamadas a la API privada.
    expect(screen.queryByLabelText("Usuario o correo")).not.toBeInTheDocument();
    expect(llamadas).toHaveLength(1);
    expect(llamadas[0]!.encabezados.Authorization).toBeUndefined();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("una constancia cancelada se indica como cancelada", async () => {
    simulador({ [`GET /api/v1/publico/verificar/${CODIGO}`]: { nombre: "Ana Pérez", folio: "CG-2026-0001", fecha_emision: "2026-01-02T12:00:00Z", estado: "CANCELADA" } });
    renderizar(<Rutas />, { ruta: `/v/${CODIGO}` });
    expect(await screen.findByText("Cancelada")).toHaveClass("error");
  });

  it("un código inexistente da un mensaje genérico", async () => {
    simulador({ [`GET /api/v1/publico/verificar/${CODIGO}`]: () => problema(404, "NO_ENCONTRADO", "No encontrado") });
    renderizar(<Rutas />, { ruta: `/v/${CODIGO}` });
    expect(await screen.findByRole("alert")).toHaveTextContent("No encontramos una constancia con este código.");
  });

  it("agrega meta de no indexar y sin Referer mientras la página está abierta", async () => {
    simulador({ [`GET /api/v1/publico/verificar/${CODIGO}`]: () => problema(404, "NO_ENCONTRADO", "No encontrado") });
    const { unmount } = renderizar(<Rutas />, { ruta: `/v/${CODIGO}` });
    await screen.findByRole("alert");
    expect(document.querySelector('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
    expect(document.querySelector('meta[name="referrer"]')).toHaveAttribute("content", "no-referrer");
    unmount();
    expect(document.querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("descarga pública /d/:token", () => {
  it("con un enlace vigente muestra el botón y no consume el enlace al abrir", async () => {
    const llamadas = simulador({ [`GET /d/${TOKEN}`]: () => new Response("<html></html>", { status: 200, headers: { "Content-Type": "text/html" } }) });
    renderizar(<Rutas />, { ruta: `/d/${TOKEN}` });

    const boton = await screen.findByRole("button", { name: "Descargar constancia" });
    const formulario = boton.closest("form")!;
    expect(formulario).toHaveAttribute("method", "post");
    expect(formulario).toHaveAttribute("action", `/d/${TOKEN}/descargar`);
    // Solo se hizo el GET (que no consume); el POST lo envía el navegador al pulsar el botón.
    expect(llamadas.map((l) => l.metodo)).toEqual(["GET"]);
    expect(llamadas[0]!.encabezados.Authorization).toBeUndefined();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("un enlace usado o vencido muestra el mensaje de enlace no válido y ningún botón", async () => {
    simulador({ [`GET /d/${TOKEN}`]: () => problema(410, "ENLACE_NO_VIGENTE", "El enlace ya se usó o venció. Solicita la constancia de nuevo.") });
    renderizar(<Rutas />, { ruta: `/d/${TOKEN}` });
    expect(await screen.findByRole("alert")).toHaveTextContent("El enlace ya se usó o venció. Solicita la constancia de nuevo.");
    expect(screen.getByRole("heading", { name: "Enlace no válido" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Descargar constancia" })).not.toBeInTheDocument();
  });

  it("un enlace inexistente da el mismo mensaje que uno vencido", async () => {
    simulador({ [`GET /d/${TOKEN}`]: () => problema(404, "NO_ENCONTRADO", "No encontrado") });
    renderizar(<Rutas />, { ruta: `/d/${TOKEN}` });
    expect(await screen.findByRole("alert")).toHaveTextContent("El enlace ya se usó o venció.");
  });

  it("si el servidor falla no se ofrece el botón", async () => {
    simulador({ [`GET /d/${TOKEN}`]: () => json({ title: "Error", status: 500, codigo: "ERROR" }, 500) });
    renderizar(<Rutas />, { ruta: `/d/${TOKEN}` });
    expect(await screen.findByRole("alert")).toHaveTextContent("No pudimos revisar el enlace");
    expect(screen.queryByRole("button", { name: "Descargar constancia" })).not.toBeInTheDocument();
  });
});
