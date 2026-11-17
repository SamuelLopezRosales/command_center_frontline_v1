import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rutas } from "@/app/rutas";
import { SesionProvider } from "@/shared/sesion/SesionProvider";
import { esperarAccesible } from "@/test/axe";
import { authSimulado, USUARIO_PRUEBA } from "@/test/ayudantes";
import type { EstadoMeta, PruebaMeta } from "./api";
import { RutasIntegraciones } from "./RutasIntegraciones";
import { json, problema, simulador, type Llamada } from "./test/simulador";

// Valores de ejemplo inventados: no son credenciales reales.
const TOKEN = "EAAprueba-no-real-0123456789abcdefWXYZ"; // pragma: allowlist secret
const APP_SECRET = "a1b2c3d4e5f60718293a4b5c6d7e8f90"; // pragma: allowlist secret
const VERIFY = "vt_Generado-Una-Sola-Vez_0123456789"; // pragma: allowlist secret

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

const VACIO: EstadoMeta = {
  configurada: false,
  waba_id: null,
  phone_number_id: null,
  api_version: "v21.0",
  access_token: { configurado: false, ultimos4: null },
  app_secret: { configurado: false, ultimos4: null },
  verify_token: { configurado: false },
  actualizado_en: null,
  actualizado_por_usuario_id: null,
};

const CONFIGURADO: EstadoMeta = {
  configurada: true,
  waba_id: "123456789012345",
  phone_number_id: "109876543210987",
  api_version: "v21.0",
  access_token: { configurado: true, ultimos4: "WXYZ" },
  app_secret: { configurado: true, ultimos4: "ef90" },
  verify_token: { configurado: true },
  actualizado_en: "2026-11-13T15:42:00Z",
  actualizado_por_usuario_id: 1,
};

const PRUEBA_OK: PruebaMeta = {
  ok: true,
  resultados: [
    { clave: "token", ok: true, detalle: "El token de acceso es válido." },
    { clave: "numero", ok: true, detalle: "Número encontrado." },
    { clave: "waba", ok: true, detalle: "Cuenta encontrada." },
    { clave: "webhook", ok: false, detalle: "Ninguna app está suscrita a la cuenta todavía." },
  ],
  numero: { nombre_verificado: "Honne Demo", numero_mostrado: "+52 55 1234 5678", calidad: "GREEN" },
  webhook_suscrito: false,
};

const yo = (permisos: string[] = ["integraciones:administrar"]) => ({ ...USUARIO_PRUEBA, permisos });

const base = (extra: Record<string, unknown> = {}) => ({
  "GET /api/v1/usuarios/yo": yo(),
  "POST /api/v1/sesion/iniciar": () => new Response(null, { status: 204 }),
  "GET /api/v1/integraciones/meta": VACIO,
  ...extra,
});

function montar(ruta = "/integraciones/meta") {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const auth = authSimulado({ haySesion: async () => true });
  const vista = render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[ruta]}>
        <SesionProvider auth={auth}>
          <Routes>
            <Route path="integraciones/*" element={<RutasIntegraciones />} />
          </Routes>
        </SesionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { cliente, ...vista };
}

const renglon = (nombre: string) => screen.getAllByRole("listitem").find((li) => li.querySelector("strong")?.textContent === nombre) as HTMLElement;
const pagina = () => screen.findByRole("heading", { name: "Conexión con Meta", level: 1 });
const guardados = (llamadas: Llamada[]) => llamadas.filter((l) => l.metodo === "PUT");

function espiarConsola() {
  return [vi.spyOn(console, "log"), vi.spyOn(console, "info"), vi.spyOn(console, "warn"), vi.spyOn(console, "error"), vi.spyOn(console, "debug")];
}

function sinSecretosEnAlmacenamiento(...valores: string[]) {
  const guardado = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
  for (const v of valores) {
    expect(guardado).not.toContain(v);
    expect(window.location.href).not.toContain(v);
  }
}

describe("estado de la conexión", () => {
  it("sin configurar: dice qué falta, muestra campos de contraseña vacíos y el aviso de validación visual", async () => {
    simulador(base());
    montar();
    await pagina();
    expect(await screen.findByText("Faltan datos")).toBeInTheDocument();
    expect(screen.getByText(/Falta capturar: WABA ID, Phone Number ID, Token de acceso permanente, App Secret, Token de verificación\./)).toBeInTheDocument();
    expect(screen.getByText("Todavía no se ha guardado ningún dato.")).toBeInTheDocument();
    expect(screen.getByText("Pantalla pendiente de validación visual con Samuel.")).toBeInTheDocument();
    for (const etiqueta of ["Token de acceso permanente", "App Secret"]) {
      const campo = screen.getByLabelText(etiqueta);
      expect(campo).toHaveAttribute("type", "password");
      expect(campo).toHaveAttribute("autocomplete", "new-password");
      expect(campo).toHaveValue("");
    }
    expect(screen.queryByRole("button", { name: /Reemplazar/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Versión de la API")).toHaveValue("v21.0");
  });

  it("configurada: enmascara los secretos con los últimos 4, no los precarga y muestra la fecha de México", async () => {
    simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO }));
    montar();
    expect(await screen.findByText("Conexión configurada")).toBeInTheDocument();
    expect(screen.getByText("Configurado · termina en ••••WXYZ")).toBeInTheDocument();
    expect(screen.getByText("Configurado · termina en ••••ef90")).toBeInTheDocument();
    // 15:42 UTC es 09:42 en la Ciudad de México.
    expect(screen.getByText(/Última actualización: 13 nov, 09:42/)).toBeInTheDocument();
    expect(screen.getByLabelText("WABA ID")).toHaveValue("123456789012345");
    expect(screen.getByLabelText("Phone Number ID")).toHaveValue("109876543210987");
    // Los secretos configurados no tienen campo de escritura hasta pulsar «Reemplazar».
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0);
  });

  it("muestra «Configurado» sin terminación cuando el servidor no entrega los últimos 4", async () => {
    simulador(base({ "GET /api/v1/integraciones/meta": { ...CONFIGURADO, access_token: { configurado: true, ultimos4: null } } }));
    montar();
    await screen.findByText("Conexión configurada");
    const enmascarados = [...document.querySelectorAll(".int-enmascarado")].map((e) => e.textContent);
    expect(enmascarados).toContain("Configurado");
    expect(enmascarados).toContain("Configurado · termina en ••••ef90");
  });

  it("cada campo tiene su ayuda junto a él y se explica que el endpoint de Meta no se edita", async () => {
    simulador(base());
    montar();
    await pagina();
    expect(await screen.findByText(/No es el número de teléfono/)).toBeInTheDocument();
    expect(screen.getByText(/Usa un token permanente de usuario del sistema/)).toBeInTheDocument();
    expect(screen.getByText(/Son 32 caracteres hexadecimales/)).toBeInTheDocument();
    expect(screen.getByText(/lo inventa el sistema/)).toBeInTheDocument();
    expect(screen.getByText(/Identificador de la cuenta de WhatsApp Business/)).toBeInTheDocument();
    expect(screen.getByText(/dura 24 horas/)).toBeInTheDocument();
    expect(screen.getByText(/lo fija el despliegue y no se edita aquí/)).toBeInTheDocument();
  });
});

describe("guardar credenciales", () => {
  it("envía solo lo escrito y distinto de lo guardado", async () => {
    const llamadas = simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO, "PUT /api/v1/integraciones/meta": () => json({ ...CONFIGURADO, phone_number_id: "555566667777" }) }));
    montar();
    await screen.findByText("Conexión configurada");
    await userEvent.clear(screen.getByLabelText("Phone Number ID"));
    await userEvent.type(screen.getByLabelText("Phone Number ID"), "555566667777");
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(await screen.findByText(/Cambios guardados/)).toBeInTheDocument();
    const puts = guardados(llamadas);
    expect(puts).toHaveLength(1);
    // Ni el WABA ID (sin cambios), ni la versión, ni los secretos (vacíos) viajan.
    expect(puts[0]!.cuerpo).toEqual({ phone_number_id: "555566667777" });
  });

  it("sin cambios no llama a la API", async () => {
    const llamadas = simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO }));
    montar();
    await screen.findByText("Conexión configurada");
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(await screen.findByText("No hay cambios que guardar: escribe al menos un dato nuevo.")).toBeInTheDocument();
    expect(guardados(llamadas)).toHaveLength(0);
  });

  it("valida los formatos en el cliente con mensajes en español y no llama a la API", async () => {
    const llamadas = simulador(base());
    montar();
    await pagina();
    await userEvent.type(await screen.findByLabelText("WABA ID"), "abc123");
    await userEvent.type(screen.getByLabelText("Phone Number ID"), "+52 55 1234");
    await userEvent.type(screen.getByLabelText("Token de acceso permanente"), "corto con espacios");
    await userEvent.type(screen.getByLabelText("App Secret"), "no-es-hexadecimal");
    await userEvent.clear(screen.getByLabelText("Versión de la API"));
    await userEvent.type(screen.getByLabelText("Versión de la API"), "21");
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect((await screen.findAllByText("Debe tener solo dígitos (de 8 a 25).")).length).toBe(2);
    expect(screen.getByText("Debe tener de 20 a 1000 caracteres, sin espacios ni saltos de línea.")).toBeInTheDocument();
    expect(screen.getByText("Debe tener 32 caracteres hexadecimales.")).toBeInTheDocument();
    expect(screen.getByText("Usa el formato v21.0 (la letra v, un número, un punto y otro).")).toBeInTheDocument();
    expect(screen.getByLabelText("WABA ID")).toHaveAttribute("aria-invalid", "true");
    expect(guardados(llamadas)).toHaveLength(0);
  });

  it("acepta los formatos válidos y muestra por campo los errores 422 del servidor", async () => {
    const llamadas = simulador(
      base({
        "PUT /api/v1/integraciones/meta": () =>
          problema(422, "VALIDACION_FALLIDA", "Datos no válidos", [
            { campo: "waba_id", codigo: "formato", mensaje: "Debe tener solo dígitos (de 8 a 25)." },
            { campo: "access_token", codigo: "formato", mensaje: "Debe tener de 20 a 1000 caracteres, sin espacios ni saltos de línea." },
          ]),
      }),
    );
    montar();
    await pagina();
    await userEvent.type(await screen.findByLabelText("WABA ID"), "12345678");
    await userEvent.type(screen.getByLabelText("Token de acceso permanente"), TOKEN);
    await userEvent.type(screen.getByLabelText("App Secret"), APP_SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(await screen.findByText("Debe tener solo dígitos (de 8 a 25).")).toBeInTheDocument();
    expect(screen.getByText("Debe tener de 20 a 1000 caracteres, sin espacios ni saltos de línea.")).toBeInTheDocument();
    expect(guardados(llamadas)[0]!.cuerpo).toEqual({ waba_id: "12345678", access_token: TOKEN, app_secret: APP_SECRET });
  });

  it("un error sin campos se muestra como alerta general", async () => {
    simulador(base({ "PUT /api/v1/integraciones/meta": () => problema(500, "ERROR_INTERNO", "No se pudo guardar en este momento.") }));
    montar();
    await userEvent.type(await screen.findByLabelText("WABA ID"), "12345678");
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo guardar en este momento.");
  });
});

describe("secretos: solo escritura", () => {
  it("tras guardar con éxito los secretos salen del DOM, del estado, del almacenamiento, de la URL, de la caché y de la consola", async () => {
    const consola = espiarConsola();
    const respuesta: EstadoMeta = { ...VACIO, configurada: false, waba_id: "12345678", access_token: { configurado: true, ultimos4: "WXYZ" }, app_secret: { configurado: true, ultimos4: "ef90" } };
    const llamadas = simulador(base({ "PUT /api/v1/integraciones/meta": () => json(respuesta) }));
    const { cliente, container } = montar();
    await pagina();
    await userEvent.type(await screen.findByLabelText("WABA ID"), "12345678");
    await userEvent.type(screen.getByLabelText("Token de acceso permanente"), TOKEN);
    await userEvent.type(screen.getByLabelText("App Secret"), APP_SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(await screen.findByText("Configurado · termina en ••••WXYZ")).toBeInTheDocument();
    expect(guardados(llamadas)[0]!.cuerpo).toEqual({ waba_id: "12345678", access_token: TOKEN, app_secret: APP_SECRET });
    // No quedan campos de contraseña ni su valor en ninguna parte del DOM.
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0);
    expect(screen.queryByDisplayValue(TOKEN)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(APP_SECRET)).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain(TOKEN);
    expect(container.innerHTML).not.toContain(APP_SECRET);
    sinSecretosEnAlmacenamiento(TOKEN, APP_SECRET);
    // La caché de consultas solo tiene lo que mandó el servidor (sin secretos) y no hay mutaciones guardadas.
    const enCache = JSON.stringify(cliente.getQueryCache().getAll().map((q) => q.state.data));
    expect(enCache).not.toContain(TOKEN);
    expect(enCache).not.toContain(APP_SECRET);
    expect(cliente.getMutationCache().getAll()).toHaveLength(0);
    for (const c of consola) expect(c).not.toHaveBeenCalled();
    // Los GET nunca llevan secretos en la URL.
    for (const l of llamadas) expect(l.url).not.toContain(TOKEN);
  });

  it("«Reemplazar» abre el campo vacío; sin escribir nada no se envía el secreto y se puede cancelar", async () => {
    const llamadas = simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO, "PUT /api/v1/integraciones/meta": () => json(CONFIGURADO) }));
    montar();
    await screen.findByText("Conexión configurada");
    await userEvent.click(screen.getByRole("button", { name: "Reemplazar: Token de acceso permanente" }));
    const campo = screen.getByLabelText("Token de acceso permanente");
    expect(campo).toHaveAttribute("type", "password");
    expect(campo).toHaveValue("");
    // Se guarda otro dato sin escribir el secreto: no viaja.
    await userEvent.clear(screen.getByLabelText("WABA ID"));
    await userEvent.type(screen.getByLabelText("WABA ID"), "99999999");
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() => expect(guardados(llamadas)).toHaveLength(1));
    expect(guardados(llamadas)[0]!.cuerpo).toEqual({ waba_id: "99999999" });
  });

  it("cancelar el reemplazo vuelve a mostrar el valor enmascarado y descarta lo escrito", async () => {
    simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO }));
    montar();
    await screen.findByText("Conexión configurada");
    await userEvent.click(screen.getByRole("button", { name: "Reemplazar: App Secret" }));
    await userEvent.type(screen.getByLabelText("App Secret"), APP_SECRET);
    await userEvent.click(screen.getByRole("button", { name: "Cancelar reemplazo" }));
    expect(screen.getByText("Configurado · termina en ••••ef90")).toBeInTheDocument();
    expect(screen.queryByDisplayValue(APP_SECRET)).not.toBeInTheDocument();
  });
});

describe("token de verificación", () => {
  it("se genera, se muestra una sola vez, se copia y desaparece al cerrar sin reaparecer", async () => {
    const consola = espiarConsola();
    const llamadas = simulador(base({ "POST /api/v1/integraciones/meta/verify-token:generar": () => json({ verify_token: VERIFY }) }));
    const escribir = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: escribir }, configurable: true });
    const { cliente, container } = montar();
    await pagina();

    await userEvent.click(await screen.findByRole("button", { name: "Generar" }));
    const confirmar = await screen.findByRole("dialog", { name: "Generar token de verificación" });
    expect(llamadas.some((l) => l.metodo === "POST" && l.ruta.endsWith("verify-token:generar"))).toBe(false);
    await userEvent.click(within(confirmar).getByRole("button", { name: "Generar token" }));

    const dialogo = await screen.findByRole("dialog", { name: "Token de verificación generado" });
    expect(within(dialogo).getByText(VERIFY)).toBeInTheDocument();
    expect(within(dialogo).getByRole("alert")).toHaveTextContent("no se podrá volver a ver");
    expect(within(dialogo).getByRole("alert")).toHaveTextContent("5 minutos");
    await userEvent.click(within(dialogo).getByRole("button", { name: "Copiar" }));
    expect(escribir).toHaveBeenCalledWith(VERIFY);
    expect(await within(dialogo).findByText("Copiado al portapapeles.")).toBeInTheDocument();
    // Mientras está abierto, el valor no está en caché ni en almacenamiento.
    expect(JSON.stringify(cliente.getQueryCache().getAll().map((q) => q.state.data))).not.toContain(VERIFY);
    expect(cliente.getMutationCache().getAll()).toHaveLength(0);

    await userEvent.click(within(dialogo).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain(VERIFY);
    expect(screen.queryByText(VERIFY)).not.toBeInTheDocument();
    sinSecretosEnAlmacenamiento(VERIFY);
    for (const c of consola) expect(c).not.toHaveBeenCalled();

    // Al volver a abrirlo no reaparece: pide confirmar de nuevo.
    await userEvent.click(screen.getByRole("button", { name: "Generar" }));
    const otro = await screen.findByRole("dialog", { name: "Generar token de verificación" });
    expect(within(otro).queryByText(VERIFY)).not.toBeInTheDocument();
  });

  it("avisa que reemplazar el token existente obliga a registrar el webhook otra vez", async () => {
    simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO }));
    montar();
    await screen.findByText("Conexión configurada");
    await userEvent.click(screen.getByRole("button", { name: "Generar" }));
    expect(await screen.findByText(/el actual deja de funcionar/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("un error al generar se muestra en el diálogo y no deja ningún valor", async () => {
    simulador(base({ "POST /api/v1/integraciones/meta/verify-token:generar": () => problema(500, "ERROR_INTERNO", "No se pudo guardar el token.") }));
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Generar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Generar token" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo guardar el token.");
  });

  it("«Usar uno propio» abre un campo de contraseña y su valor viaja como verify_token", async () => {
    const llamadas = simulador(base({ "PUT /api/v1/integraciones/meta": () => json({ ...VACIO, verify_token: { configurado: true } }) }));
    montar();
    await pagina();
    await userEvent.click(await screen.findByRole("button", { name: "Usar uno propio" }));
    const campo = screen.getByLabelText("Token de verificación");
    expect(campo).toHaveAttribute("type", "password");
    await userEvent.type(campo, "corto");
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(await screen.findByText("Debe tener de 16 a 128 caracteres: letras, números, guion y guion bajo.")).toBeInTheDocument();
    await userEvent.clear(campo);
    await userEvent.type(campo, VERIFY);
    await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() => expect(guardados(llamadas)).toHaveLength(1));
    expect(guardados(llamadas)[0]!.cuerpo).toEqual({ verify_token: VERIFY });
    await waitFor(() => expect(screen.queryByDisplayValue(VERIFY)).not.toBeInTheDocument());
  });
});

describe("URL del webhook", () => {
  it("muestra la URL del mismo dominio, se copia y lista los campos a suscribir", async () => {
    simulador(base());
    const escribir = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: escribir }, configurable: true });
    montar();
    await pagina();
    const url = `${window.location.origin}/webhook/meta`;
    const bloque = await screen.findByRole("region", { name: "URL del webhook" });
    expect(within(bloque).getByText(url)).toBeInTheDocument();
    expect(within(bloque).getByText("messages")).toBeInTheDocument();
    expect(within(bloque).getByText("message_template_status_update")).toBeInTheDocument();
    await userEvent.click(within(bloque).getByRole("button", { name: "Copiar URL" }));
    expect(escribir).toHaveBeenCalledWith(url);
    expect(await within(bloque).findByText("URL copiada.")).toBeInTheDocument();
  });
});

describe("probar conexión", () => {
  const probar = async () => userEvent.click(await screen.findByRole("button", { name: "Probar conexión" }));

  it("con éxito muestra los renglones con ícono y texto, los datos del número y el webhook aparte", async () => {
    const llamadas = simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO, "POST /api/v1/integraciones/meta/probar": PRUEBA_OK }));
    montar();
    await probar();
    const resultado = await screen.findByText("Token, número y cuenta son válidos.");
    const zona = within(resultado.closest(".int-resultado") as HTMLElement);
    const items = zona.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent("Token de acceso: Correcto");
    expect(items[1]).toHaveTextContent("Número de WhatsApp: Correcto");
    expect(items[2]).toHaveTextContent("Cuenta de WhatsApp Business: Correcto");
    // El webhook sin suscribir es lo esperado antes de registrarlo: «Pendiente», no «Falló».
    expect(items[3]).toHaveTextContent("Webhook: Pendiente");
    expect(items[3]).toHaveTextContent("Ninguna app está suscrita a la cuenta todavía.");
    expect(zona.getByText("Honne Demo")).toBeInTheDocument();
    expect(zona.getByText("+52 55 1234 5678")).toBeInTheDocument();
    expect(zona.getByText("GREEN")).toBeInTheDocument();
    expect(zona.getByText(/es normal que salga «sin suscribir»/)).toBeInTheDocument();
    expect(llamadas.filter((l) => l.metodo === "POST" && l.ruta.endsWith("/probar"))).toHaveLength(1);
  });

  it("con el webhook suscrito lo marca como correcto", async () => {
    const prueba: PruebaMeta = { ...PRUEBA_OK, webhook_suscrito: true, resultados: PRUEBA_OK.resultados.map((r) => (r.clave === "webhook" ? { ...r, ok: true, detalle: "Hay una app suscrita." } : r)) };
    simulador(base({ "POST /api/v1/integraciones/meta/probar": prueba }));
    montar();
    await probar();
    await screen.findByText("Token, número y cuenta son válidos.");
    expect(renglon("Webhook")).toHaveTextContent("Webhook: Correcto");
  });

  it("un renglón fallido muestra su mensaje en español y el resumen pide corregir", async () => {
    const prueba: PruebaMeta = {
      ok: false,
      resultados: [
        { clave: "token", ok: false, detalle: "Meta rechazó el token de acceso: no es válido o ya venció." },
        { clave: "numero", ok: true, detalle: "Número encontrado." },
      ],
      numero: null,
      webhook_suscrito: null,
    };
    simulador(base({ "POST /api/v1/integraciones/meta/probar": prueba }));
    montar();
    await probar();
    expect(await screen.findByText("Hay datos por corregir (revisa los renglones marcados).")).toBeInTheDocument();
    expect(renglon("Token de acceso")).toHaveTextContent("Token de acceso: Falló");
    expect(renglon("Token de acceso")).toHaveTextContent("Meta rechazó el token de acceso: no es válido o ya venció.");
    // Lo que no vino en la respuesta se marca como no probado, no como correcto.
    expect(renglon("Cuenta de WhatsApp Business")).toHaveTextContent("No probado");
    expect(renglon("Webhook")).toHaveTextContent("No probado");
  });

  it("META_NO_CONFIGURADA guía a guardar primero los datos", async () => {
    simulador(base({ "POST /api/v1/integraciones/meta/probar": () => problema(422, "META_NO_CONFIGURADA", "Faltan datos de Meta.") }));
    montar();
    await probar();
    expect(await screen.findByRole("alert")).toHaveTextContent("Guarda primero el WABA ID, el Phone Number ID y el token de acceso");
  });

  it("otro error se muestra con el mensaje del servidor", async () => {
    simulador(base({ "POST /api/v1/integraciones/meta/probar": () => problema(502, "META_NO_DISPONIBLE", "No se pudo contactar a Meta.") }));
    montar();
    await probar();
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo contactar a Meta.");
  });
});

describe("permisos y navegación", () => {
  it("sin integraciones:administrar la ruta muestra acceso denegado y no consulta la API de Meta", async () => {
    const llamadas = simulador(base({ "GET /api/v1/usuarios/yo": yo(["chat:responder"]) }));
    montar();
    expect(await screen.findByText("No tienes permiso para administrar la conexión con Meta.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.ruta.startsWith("/api/v1/integraciones"))).toBe(false);
  });

  function montarApp(permisos: string[], ruta = "/") {
    simulador(base({ "GET /api/v1/usuarios/yo": yo(permisos) }));
    const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={cliente}>
        <MemoryRouter initialEntries={[ruta]}>
          <SesionProvider auth={authSimulado({ haySesion: async () => true })}>
            <Rutas />
          </SesionProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("el menú muestra «Meta» solo con el permiso y lleva a la pantalla", async () => {
    montarApp(["integraciones:administrar"]);
    const nav = await screen.findByRole("navigation", { name: "Principal" });
    await userEvent.click(within(nav).getByRole("link", { name: "Meta" }));
    expect(await screen.findByRole("heading", { name: "Conexión con Meta", level: 1 })).toBeInTheDocument();
  });

  it("el menú no muestra «Meta» sin el permiso y la ruta directa da acceso denegado", async () => {
    montarApp(["colaboradores:ver"]);
    const nav = await screen.findByRole("navigation", { name: "Principal" });
    expect(within(nav).queryByRole("link", { name: "Meta" })).not.toBeInTheDocument();
  });

  it("entrar por la URL sin permiso muestra acceso denegado dentro del shell", async () => {
    montarApp(["colaboradores:ver"], "/integraciones/meta");
    expect(await screen.findByText("No tienes permiso para administrar la conexión con Meta.")).toBeInTheDocument();
  });
});

describe("enlace desde plantillas de mensaje", () => {
  function montarPlantillas(permisos: string[], estado: EstadoMeta | null) {
    simulador({
      "GET /api/v1/usuarios/yo": yo(permisos),
      "POST /api/v1/sesion/iniciar": () => new Response(null, { status: 204 }),
      "GET /api/v1/plantillas-mensaje": { items: [], siguiente: null },
      ...(estado ? { "GET /api/v1/integraciones/meta": estado } : {}),
    });
    return montarApp(permisos, "/notificaciones/plantillas");
  }
  function montarApp(_permisos: string[], ruta: string) {
    const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={cliente}>
        <MemoryRouter initialEntries={[ruta]}>
          <SesionProvider auth={authSimulado({ haySesion: async () => true })}>
            <Rutas />
          </SesionProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("con el permiso ofrece el enlace y avisa si la conexión no está configurada", async () => {
    montarPlantillas(["integraciones:administrar", "notificaciones:administrar"], VACIO);
    expect(await screen.findByRole("note")).toHaveTextContent("La conexión con Meta no está configurada");
    expect(screen.getAllByRole("link", { name: "Conexión con Meta" }).length).toBeGreaterThanOrEqual(2);
  });

  it("si la conexión está configurada no hay aviso, solo el enlace", async () => {
    montarPlantillas(["integraciones:administrar"], CONFIGURADO);
    await screen.findByText("Aún no hay plantillas de mensaje. Crea la primera.");
    expect(screen.getAllByRole("link", { name: "Conexión con Meta" }).length).toBe(1);
    expect(screen.queryByText(/no está configurada/)).not.toBeInTheDocument();
  });

  it("sin el permiso no hay enlace ni se consulta la conexión", async () => {
    montarPlantillas(["notificaciones:administrar"], null);
    await screen.findByText("Aún no hay plantillas de mensaje. Crea la primera.");
    expect(screen.queryByRole("link", { name: "Conexión con Meta" })).not.toBeInTheDocument();
  });
});

describe("accesibilidad", () => {
  it("la pantalla sin configurar no tiene violaciones críticas ni serias", async () => {
    simulador(base());
    const { container } = montar();
    await pagina();
    await screen.findByRole("button", { name: "Probar conexión" });
    await esperarAccesible(container);
  });

  it("la pantalla configurada, con una prueba fallida y el diálogo abierto, tampoco", async () => {
    simulador(base({ "GET /api/v1/integraciones/meta": CONFIGURADO, "POST /api/v1/integraciones/meta/probar": PRUEBA_OK, "POST /api/v1/integraciones/meta/verify-token:generar": () => json({ verify_token: VERIFY }) }));
    const { container } = montar();
    await userEvent.click(await screen.findByRole("button", { name: "Probar conexión" }));
    await screen.findByText("Token, número y cuenta son válidos.");
    await userEvent.click(screen.getByRole("button", { name: "Generar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Generar token" }));
    await screen.findByRole("dialog", { name: "Token de verificación generado" });
    await esperarAccesible(container);
  });
});
