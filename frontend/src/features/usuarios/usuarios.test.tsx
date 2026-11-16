import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { authSimulado, renderizar, USUARIO_PRUEBA } from "@/test/ayudantes";
import type { RegistroBitacora, UsuarioItem } from "./api";
import { RutasUsuarios } from "./RutasUsuarios";
import { json, problema, simulador } from "./test/simulador";
import { esperarAccesible } from "@/test/axe";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

const usuario = (sobre: Partial<UsuarioItem>): UsuarioItem => ({
  id: 1,
  nombre: "David Bet",
  correo: "david@empresa.com",
  rol: "RH",
  activo: true,
  ultima_actividad: "2026-11-13T15:42:00Z",
  fecha_creacion: "2026-01-02T10:00:00Z",
  ...sobre,
});

const USUARIOS = {
  items: [
    usuario({ id: 1 }),
    usuario({ id: 2, nombre: "Lucía Mora", correo: "lucia@empresa.com" }),
    usuario({ id: 3, nombre: "Pedro Ruiz", correo: "pedro@empresa.com", activo: false, ultima_actividad: null }),
  ],
};

const yo = (permisos = ["usuarios:administrar", "bitacora:ver"]) => ({ ...USUARIO_PRUEBA, permisos });

const base = (extra: Record<string, unknown> = {}) => ({
  "GET /api/v1/usuarios/yo": yo(),
  "POST /api/v1/sesion/iniciar": () => new Response(null, { status: 204 }),
  "GET /api/v1/usuarios": USUARIOS,
  ...extra,
});

function montar(ruta = "/usuarios") {
  return renderizar(
    <Routes>
      <Route path="usuarios/*" element={<RutasUsuarios />} />
    </Routes>,
    { ruta, auth: authSimulado({ haySesion: async () => true }) },
  );
}

const fila = (nombre: string) => within(screen.getByText(nombre).closest("tr")!);

describe("usuarios (DSH-08)", () => {
  it("lista los usuarios con su estado activo o inactivo", async () => {
    simulador(base());
    montar();
    const tabla = await screen.findByRole("table", { name: "Usuarios de la empresa" });
    expect(within(tabla).getByText("lucia@empresa.com")).toBeInTheDocument();
    expect(fila("Lucía Mora").getByText("Activo")).toBeInTheDocument();
    expect(fila("Pedro Ruiz").getByText("Inactivo")).toBeInTheDocument();
    expect(fila("Pedro Ruiz").getByText("Sin actividad")).toBeInTheDocument();
    // 15:42 UTC es 09:42 en la Ciudad de México.
    expect(fila("Lucía Mora").getByText("13 nov, 09:42")).toBeInTheDocument();
  });

  it("no ofrece desactivarse a uno mismo ni desactivar a quien ya está inactivo", async () => {
    simulador(base());
    montar();
    await screen.findByText("Lucía Mora");
    expect(fila("David Bet").queryByRole("button")).not.toBeInTheDocument();
    expect(fila("David Bet").getByText("(tú)")).toBeInTheDocument();
    expect(fila("Pedro Ruiz").queryByRole("button")).not.toBeInTheDocument();
    expect(fila("Lucía Mora").getByRole("button", { name: "Desactivar Lucía Mora" })).toBeInTheDocument();
  });

  it("sin el permiso usuarios:administrar no consulta la lista", async () => {
    const llamadas = simulador(base({ "GET /api/v1/usuarios/yo": yo(["chat:responder"]) }));
    montar();
    expect(await screen.findByText("No tienes permiso para administrar usuarios.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.ruta === "/api/v1/usuarios")).toBe(false);
  });
});

describe("desactivar usuario (DSH-09)", () => {
  it("pide confirmación y desactiva; cancelar no llama a la API", async () => {
    const llamadas = simulador(base({ "POST /api/v1/usuarios/2/desactivar": () => new Response(null, { status: 204 }) }));
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Desactivar Lucía Mora" }));
    const dialogo = await screen.findByRole("dialog", { name: "Desactivar usuario" });
    expect(within(dialogo).getByText(/¿Desactivar a Lucía Mora\?/)).toBeInTheDocument();
    await userEvent.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST" && l.ruta !== "/api/v1/sesion/iniciar")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Desactivar Lucía Mora" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Desactivar usuario" }));
    expect(await screen.findByText("Se desactivó a Lucía Mora. Sus sesiones se cerraron.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(llamadas.filter((l) => l.metodo === "POST" && l.ruta === "/api/v1/usuarios/2/desactivar")).toHaveLength(1);
    // La lista se vuelve a leer.
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "GET" && l.ruta === "/api/v1/usuarios").length).toBeGreaterThan(1));
  });

  it.each([
    ["ULTIMO_USUARIO_ACTIVO", "La empresa debe conservar al menos un usuario activo."],
    ["NO_PUEDE_DESACTIVARSE", "No puedes desactivar tu propia cuenta."],
  ])("409 %s se explica con un mensaje claro y deja el diálogo abierto", async (codigo, mensaje) => {
    simulador(base({ "POST /api/v1/usuarios/2/desactivar": () => problema(409, codigo, "Conflicto") }));
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Desactivar Lucía Mora" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Desactivar usuario" }));
    const dialogo = await screen.findByRole("dialog");
    expect(await within(dialogo).findByRole("alert")).toHaveTextContent(mensaje);
  });
});

describe("invitaciones (DSH-10)", () => {
  const CODIGO = "INV-ZXCV-9876-QWER";
  const respuesta = { id: 5, codigo: CODIGO, fecha_expira: "2026-11-20T18:00:00Z" };

  it("muestra el código una sola vez, lo copia y lo descarta al cerrar sin dejarlo en ningún lado", async () => {
    const consola = [vi.spyOn(console, "log"), vi.spyOn(console, "info"), vi.spyOn(console, "warn"), vi.spyOn(console, "error"), vi.spyOn(console, "debug")];
    const llamadas = simulador(base({ "POST /api/v1/usuarios/invitaciones": () => json(respuesta, 201) }));
    const escribir = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: escribir }, configurable: true });
    montar();

    await userEvent.click(await screen.findByRole("button", { name: "Invitar usuario" }));
    await userEvent.type(screen.getByLabelText("Correo de la persona invitada (opcional)"), "nueva@empresa.com");
    await userEvent.click(screen.getByRole("button", { name: "Crear invitación" }));

    const dialogo = await screen.findByRole("dialog", { name: "Invitación creada" });
    expect(within(dialogo).getByText(CODIGO)).toBeInTheDocument();
    expect(within(dialogo).getByText(/no se podrá volver a ver/)).toBeInTheDocument();
    expect(within(dialogo).getByText(/Vence el 20 nov, 12:00/)).toBeInTheDocument();
    expect(llamadas.find((l) => l.metodo === "POST" && l.ruta === "/api/v1/usuarios/invitaciones")!.cuerpo).toEqual({ correo_destino: "nueva@empresa.com" });

    await userEvent.click(within(dialogo).getByRole("button", { name: "Copiar código" }));
    expect(escribir).toHaveBeenCalledWith(CODIGO);
    expect(await within(dialogo).findByText("Código copiado.")).toBeInTheDocument();

    await userEvent.click(within(dialogo).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Ni en el DOM, ni en storage, ni en la URL, ni en la consola.
    expect(document.body.textContent).not.toContain(CODIGO);
    expect(JSON.stringify({ ...localStorage })).not.toContain(CODIGO);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(CODIGO);
    expect(window.location.href).not.toContain(CODIGO);
    for (const espia of consola) expect(JSON.stringify(espia.mock.calls)).not.toContain(CODIGO);

    // Abrir de nuevo empieza de cero: no reaparece el código anterior.
    await userEvent.click(screen.getByRole("button", { name: "Invitar usuario" }));
    expect(await screen.findByRole("dialog", { name: "Invitar usuario" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(CODIGO);
  });

  it("el correo es opcional: sin correo se envía un cuerpo vacío", async () => {
    const llamadas = simulador(base({ "POST /api/v1/usuarios/invitaciones": () => json(respuesta, 201) }));
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Invitar usuario" }));
    await userEvent.click(screen.getByRole("button", { name: "Crear invitación" }));
    await screen.findByRole("dialog", { name: "Invitación creada" });
    expect(llamadas.find((l) => l.metodo === "POST" && l.ruta === "/api/v1/usuarios/invitaciones")!.cuerpo).toEqual({});
  });

  it("valida el correo antes de llamar a la API y muestra los errores del servidor", async () => {
    const llamadas = simulador(base({ "POST /api/v1/usuarios/invitaciones": () => problema(500, "ERROR_INTERNO", "No se pudo crear la invitación.") }));
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Invitar usuario" }));
    await userEvent.type(screen.getByLabelText("Correo de la persona invitada (opcional)"), "no-es-correo");
    await userEvent.click(screen.getByRole("button", { name: "Crear invitación" }));
    expect(await screen.findByText("Escribe un correo válido.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST" && l.ruta !== "/api/v1/sesion/iniciar")).toBe(false);

    await userEvent.clear(screen.getByLabelText("Correo de la persona invitada (opcional)"));
    await userEvent.click(screen.getByRole("button", { name: "Crear invitación" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo crear la invitación.");
    expect(screen.getByRole("dialog", { name: "Invitar usuario" })).toBeInTheDocument();
  });

  it("Escape cierra el diálogo con el código y lo descarta", async () => {
    simulador(base({ "POST /api/v1/usuarios/invitaciones": () => json(respuesta, 201) }));
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Invitar usuario" }));
    await userEvent.click(screen.getByRole("button", { name: "Crear invitación" }));
    await screen.findByText(CODIGO);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(CODIGO);
  });
});

describe("bitácora (DSH-05)", () => {
  const registro = (sobre: Partial<RegistroBitacora>): RegistroBitacora => ({
    id: 1,
    fecha_hora: "2026-11-13T15:42:00Z",
    usuario_id: 1,
    usuario_nombre: "David Bet",
    colaborador_id: null,
    accion: "USUARIO_DESACTIVADO",
    entidad: "usuario",
    entidad_id: 2,
    ip: "10.0.0.1",
    origen: "WEB",
    detalle: {},
    ...sobre,
  });

  it("se enlaza desde usuarios, lista los registros y aplica los filtros", async () => {
    const llamadas = simulador(
      base({
        "GET /api/v1/bitacora": { items: [registro({}), registro({ id: 2, usuario_id: null, usuario_nombre: null, accion: "CONSTANCIA_GENERADA", entidad: "constancia", entidad_id: null, ip: null })], siguiente: null },
      }),
    );
    montar();
    await userEvent.click(await screen.findByRole("link", { name: "Ver bitácora" }));
    const tabla = await screen.findByRole("table", { name: "Registros de la bitácora" });
    const primera = within(within(tabla).getByText("Usuario desactivado").closest("tr")!);
    expect(primera.getByText("David Bet")).toBeInTheDocument();
    expect(primera.getByText("usuario #2")).toBeInTheDocument();
    expect(primera.getByText("13 nov, 09:42")).toBeInTheDocument();
    expect(within(within(tabla).getByText("Constancia generada").closest("tr")!).getByText("Sistema")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Acción"), "ALTA");
    await userEvent.selectOptions(screen.getByLabelText("Orden"), "asc");
    await userEvent.type(screen.getByLabelText("Desde"), "2026-11-01");
    await waitFor(() => {
      const url = llamadas.filter((l) => l.ruta === "/api/v1/bitacora").at(-1)!.url;
      expect(url).toContain("accion=ALTA");
      expect(url).toContain("orden=asc");
      expect(url).toContain("desde=2026-11-01T06%3A00%3A00.000Z");
    });
  });

  it("sin el permiso bitacora:ver no ofrece el enlace ni consulta", async () => {
    const llamadas = simulador(base({ "GET /api/v1/usuarios/yo": yo(["usuarios:administrar"]) }));
    montar();
    await screen.findByText("Lucía Mora");
    expect(screen.queryByRole("link", { name: "Ver bitácora" })).not.toBeInTheDocument();
    expect(llamadas.some((l) => l.ruta === "/api/v1/bitacora")).toBe(false);
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("usuarios, invitación y bitácora no tienen violaciones críticas ni serias de axe", async () => {
    simulador(
      base({
        "POST /api/v1/usuarios/invitaciones": () => json({ id: 5, codigo: "INV-ZXCV-9876-QWER", fecha_expira: "2026-11-20T18:00:00Z" }, 201),
        "GET /api/v1/bitacora": {
          items: [
            { id: 1, fecha_hora: "2026-11-13T15:42:00Z", usuario_id: 1, usuario_nombre: "David Bet", colaborador_id: null, accion: "USUARIO_DESACTIVADO", entidad: "usuario", entidad_id: 2, ip: "10.0.0.1", origen: "WEB", detalle: {} },
          ],
          siguiente: null,
        },
      }),
    );
    const { container } = montar();
    await screen.findByRole("table", { name: "Usuarios de la empresa" });
    await esperarAccesible(container);
    await userEvent.click(screen.getByRole("button", { name: "Invitar usuario" }));
    await userEvent.click(screen.getByRole("button", { name: "Crear invitación" }));
    await screen.findByRole("dialog", { name: "Invitación creada" });
    await esperarAccesible(container);
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Cerrar|Listo|Entendido/ }));
    await userEvent.click(await screen.findByRole("link", { name: "Ver bitácora" }));
    await screen.findByRole("table", { name: "Registros de la bitácora" });
    await esperarAccesible(container);
  });
});

describe("fechas en la zona de México (CC-NFR-014)", () => {
  it("la bitácora muestra la hora de México: 03:30 UTC es 21:30 del día anterior", async () => {
    simulador(
      base({
        "GET /api/v1/bitacora": {
          items: [{ id: 1, fecha_hora: "2026-11-14T03:30:00Z", usuario_id: 1, usuario_nombre: "David Bet", colaborador_id: null, accion: "USUARIO_DESACTIVADO", entidad: "usuario", entidad_id: 2, ip: null, origen: "WEB", detalle: {} }],
          siguiente: null,
        },
      }),
    );
    montar("/usuarios/bitacora");
    const tabla = await screen.findByRole("table", { name: "Registros de la bitácora" });
    expect(within(tabla).getByText("13 nov, 21:30")).toBeInTheDocument();
  });
});
