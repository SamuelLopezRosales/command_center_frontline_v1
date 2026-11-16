import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";
import { Rutas } from "./rutas";
import { USUARIO_PRUEBA, authSimulado, renderizar, simularApi } from "@/test/ayudantes";
import { ErrorAcceso, type PasoAcceso } from "@/shared/sesion/servicioAuth";
import { esperarAccesible } from "@/test/axe";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const api = () => simularApi({ "/api/v1/usuarios/yo": USUARIO_PRUEBA, "/api/v1/sesion/iniciar": undefined });

describe("acceso con MFA", () => {
  it("correo y contraseña, código TOTP y entrada al dashboard", async () => {
    api();
    const usuario = userEvent.setup();
    let sesion = false;
    const auth = authSimulado({
      iniciarSesion: async () => ({ paso: "TOTP" }) as PasoAcceso,
      confirmarTotp: async () => {
        sesion = true;
        return { paso: "LISTO" } as PasoAcceso;
      },
      haySesion: async () => sesion,
    });
    renderizar(<Rutas />, { auth, ruta: "/acceso" });

    await usuario.type(await screen.findByLabelText("Usuario o correo"), "david@empresa.com");
    await usuario.type(screen.getByLabelText("Contraseña"), "Contrasena-Larga-1!");
    await usuario.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    await usuario.type(await screen.findByLabelText("Código de verificación"), "123456");
    await usuario.click(screen.getByRole("button", { name: "Verificar" }));

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText("David Bet")).toBeInTheDocument();
  });

  it("primer inicio: muestra el QR y la clave de enrolamiento", async () => {
    const auth = authSimulado({
      iniciarSesion: async () => ({ paso: "ENROLAR_TOTP", uriQr: "otpauth://totp/CC:x?secret=ABCD", clave: "ABCD1234" }) as PasoAcceso,
    });
    const usuario = userEvent.setup();
    renderizar(<Rutas />, { auth, ruta: "/acceso" });
    await usuario.type(await screen.findByLabelText("Usuario o correo"), "nuevo@empresa.com");
    await usuario.type(screen.getByLabelText("Contraseña"), "Contrasena-Larga-1!");
    await usuario.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    expect(await screen.findByText("Configura tu aplicación autenticadora")).toBeInTheDocument();
    expect(screen.getByText("ABCD1234")).toBeInTheDocument();
    expect(screen.getByTitle("Código QR de la aplicación autenticadora")).toBeInTheDocument();
  });

  it("credenciales incorrectas: mensaje genérico sin pista del campo", async () => {
    const auth = authSimulado({
      iniciarSesion: async () => {
        throw new ErrorAcceso("CREDENCIALES", "Correo o contraseña incorrectos.");
      },
    });
    const usuario = userEvent.setup();
    renderizar(<Rutas />, { auth, ruta: "/acceso" });
    await usuario.type(await screen.findByLabelText("Usuario o correo"), "x@empresa.com");
    await usuario.type(screen.getByLabelText("Contraseña"), "mala");
    await usuario.click(screen.getByRole("button", { name: "Iniciar sesión" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Correo o contraseña incorrectos.");
  });

  it("valida el formato del código TOTP antes de enviarlo", async () => {
    const auth = authSimulado({ iniciarSesion: async () => ({ paso: "TOTP" }) as PasoAcceso });
    const usuario = userEvent.setup();
    renderizar(<Rutas />, { auth, ruta: "/acceso" });
    await usuario.type(await screen.findByLabelText("Usuario o correo"), "a@b.com");
    await usuario.type(screen.getByLabelText("Contraseña"), "x");
    await usuario.click(screen.getByRole("button", { name: "Iniciar sesión" }));
    await usuario.type(await screen.findByLabelText("Código de verificación"), "12");
    await usuario.click(screen.getByRole("button", { name: "Verificar" }));
    expect(await screen.findByText("El código tiene 6 dígitos.")).toBeInTheDocument();
    expect(auth.llamadas).not.toContain("confirmarTotp");
  });

  it("sin sesión, las rutas protegidas llevan al acceso", async () => {
    renderizar(<Rutas />, { ruta: "/colaboradores" });
    expect(await screen.findByLabelText("Usuario o correo")).toBeInTheDocument();
  });
});

describe("registro con invitación", () => {
  it("pide el código de invitación y luego confirma el correo", async () => {
    const auth = authSimulado();
    const usuario = userEvent.setup();
    renderizar(<Rutas />, { auth, ruta: "/registro" });
    await usuario.type(await screen.findByLabelText("Nombre completo"), "Ana Pérez");
    await usuario.type(screen.getByLabelText("Usuario o correo"), "ana@empresa.com");
    await usuario.type(screen.getByLabelText("Contraseña"), "Contrasena-Larga-1!");
    await usuario.type(screen.getByLabelText("Código de invitación"), "ABC-123");
    await usuario.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await usuario.type(await screen.findByLabelText("Código del correo"), "654321");
    await usuario.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(auth.llamadas).toEqual(["registrar", "confirmarRegistro"]));
  });

  it("rechaza una contraseña sin la política", async () => {
    const usuario = userEvent.setup();
    renderizar(<Rutas />, { ruta: "/registro" });
    await usuario.type(await screen.findByLabelText("Nombre completo"), "Ana");
    await usuario.type(screen.getByLabelText("Usuario o correo"), "ana@empresa.com");
    await usuario.type(screen.getByLabelText("Contraseña"), "soloMinusculasLargas");
    await usuario.type(screen.getByLabelText("Código de invitación"), "X");
    await usuario.click(screen.getByRole("button", { name: "Crear cuenta" }));
    expect((await screen.findAllByText(/Mínimo 12 caracteres con mayúscula/)).length).toBeGreaterThan(0);
  });
});

describe("registro abierto (ambientes de prueba)", () => {
  it("no pide el código de invitación y registra sin él", async () => {
    let recibido: unknown = null;
    const auth = authSimulado({
      registroAbierto: true,
      registrar: async (d) => {
        recibido = d;
        return { requiereConfirmacion: true };
      },
    });
    const usuario = userEvent.setup();
    renderizar(<Rutas />, { auth, ruta: "/registro" });
    await usuario.type(await screen.findByLabelText("Nombre completo"), "Ana Pérez");
    expect(screen.queryByLabelText("Código de invitación")).toBeNull();
    await usuario.type(screen.getByLabelText("Usuario o correo"), "ana@honne.com");
    await usuario.type(screen.getByLabelText("Contraseña"), "Contrasena-Larga-1!");
    await usuario.click(screen.getByRole("button", { name: "Crear cuenta" }));
    expect(await screen.findByLabelText("Código del correo")).toBeTruthy();
    expect(recibido).toMatchObject({ correo: "ana@honne.com", nombre: "Ana Pérez" });
  });
});
describe("recuperación de contraseña", () => {
  it("envía el código y restablece", async () => {
    const auth = authSimulado();
    const usuario = userEvent.setup();
    renderizar(<Rutas />, { auth, ruta: "/recuperar" });
    await usuario.type(await screen.findByLabelText("Usuario o correo"), "ana@empresa.com");
    await usuario.click(screen.getByRole("button", { name: "Enviar código" }));
    await usuario.type(await screen.findByLabelText("Código del correo"), "111222");
    await usuario.type(screen.getByLabelText("Nueva contraseña"), "Nueva-Contrasena-9!");
    await usuario.click(screen.getByRole("button", { name: "Restablecer contraseña" }));
    await waitFor(() => expect(auth.llamadas).toEqual(["solicitarRecuperacion", "restablecerContrasena"]));
  });
});

describe("navegación y sesión", () => {
  const conSesion = () => authSimulado({ haySesion: async () => true });

  it("el menú muestra Dashboard, Colaboradores, Constancias y Notificaciones", async () => {
    api();
    renderizar(<Rutas />, { auth: conSesion() });
    const nav = await screen.findByRole("navigation", { name: "Principal" });
    expect(nav).toHaveTextContent("Dashboard");
    expect(nav).toHaveTextContent("Colaboradores");
    expect(nav).toHaveTextContent("Constancias");
    expect(nav).toHaveTextContent("Notificaciones");
  });

  it("la sesión se cierra tras 30 minutos sin actividad", async () => {
    api();
    const auth = conSesion();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderizar(<Rutas />, { auth });
    await screen.findByRole("navigation", { name: "Principal" });
    await act(async () => {}); // vacía los efectos pendientes: ahí se registra el temporizador
    await act(async () => {
      vi.advanceTimersByTime(30 * 60 * 1000 + 100);
    });
    // El cierre es asíncrono (cerrarSesion y luego el estado): se espera la llamada y luego el aviso.
    await waitFor(() => expect(auth.llamadas).toContain("cerrarSesion"), { timeout: 5000 });
    expect(await screen.findByText("Tu sesión se cerró por inactividad.", {}, { timeout: 5000 })).toBeInTheDocument();
  });

  it("la actividad del usuario reinicia el temporizador", async () => {
    api();
    const auth = conSesion();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderizar(<Rutas />, { auth });
    await screen.findByRole("navigation", { name: "Principal" });
    await act(async () => {});
    await act(async () => {
      vi.advanceTimersByTime(29 * 60 * 1000);
      window.dispatchEvent(new Event("mousemove"));
      vi.advanceTimersByTime(29 * 60 * 1000);
    });
    expect(auth.llamadas).not.toContain("cerrarSesion");
  });

  it("los tokens no se guardan en localStorage", async () => {
    api();
    renderizar(<Rutas />, { auth: conSesion() });
    await screen.findByRole("navigation", { name: "Principal" });
    expect(window.localStorage.length).toBe(0);
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el acceso (usuario y contraseña, y paso del código MFA) no tiene violaciones críticas ni serias de axe", async () => {
    const auth = authSimulado({ iniciarSesion: async () => ({ paso: "TOTP" }) as PasoAcceso });
    const usuario = userEvent.setup();
    const { container } = renderizar(<Rutas />, { auth, ruta: "/acceso" });
    await usuario.type(await screen.findByLabelText("Usuario o correo"), "a@b.com");
    await esperarAccesible(container);
    await usuario.type(screen.getByLabelText("Contraseña"), "x");
    await usuario.click(screen.getByRole("button", { name: "Iniciar sesión" }));
    await screen.findByLabelText("Código de verificación");
    await esperarAccesible(container);
  });
});
