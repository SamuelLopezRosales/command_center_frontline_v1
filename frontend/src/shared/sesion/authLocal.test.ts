import { describe, expect, it, vi } from "vitest";
import { crearAuthLocal } from "./authLocal";
import { ErrorAcceso } from "./servicioAuth";

function almacenEnMemoria() {
  const datos = new Map<string, string>();
  return {
    getItem: (k: string) => datos.get(k) ?? null,
    setItem: (k: string, v: string) => void datos.set(k, v),
    removeItem: (k: string) => void datos.delete(k),
  };
}

function tokenConExp(exp: number): string {
  const carga = btoa(JSON.stringify({ exp })).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `cabecera.${carga}.firma`;
}

const respuesta = (cuerpo: unknown, estado = 200) => new Response(JSON.stringify(cuerpo), { status: estado });

describe("acceso de desarrollo local", () => {
  it("sigue el flujo real: credenciales, paso TOTP y token en el almacén de la pestaña", async () => {
    const vigente = tokenConExp(Math.floor(Date.now() / 1000) + 3600);
    const f = vi
      .fn()
      .mockResolvedValueOnce(respuesta({ paso: "TOTP", sesion: "s-1" }))
      .mockResolvedValueOnce(respuesta({ access_token: vigente, expira_en: 3600 }));
    const almacen = almacenEnMemoria();
    const auth = crearAuthLocal({ fetch: f as never, almacen });

    expect(await auth.haySesion()).toBe(false);
    expect(await auth.iniciarSesion("ana.rh@demo.test", "x")).toEqual({ paso: "TOTP" });
    expect(await auth.confirmarTotp("123456")).toEqual({ paso: "LISTO" });

    expect(f.mock.calls[0][0]).toBe("/api/dev/auth/iniciar");
    expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ sesion: "s-1", codigo: "123456" });
    expect(await auth.haySesion()).toBe(true);
    expect(await auth.token()).toBe(vigente);

    await auth.cerrarSesion();
    expect(await auth.haySesion()).toBe(false);
    expect(await auth.token()).toBeNull();
  });

  it("credenciales incorrectas dan el mismo error que el acceso real", async () => {
    const f = vi.fn().mockResolvedValue(respuesta({ codigo: "CREDENCIALES" }, 401));
    const auth = crearAuthLocal({ fetch: f as never, almacen: almacenEnMemoria() });
    const error = await auth.iniciarSesion("a@b.test", "mal").catch((e) => e);
    expect(error).toBeInstanceOf(ErrorAcceso);
    expect(error.codigo).toBe("CREDENCIALES");
  });

  it("un código que no son 6 dígitos se rechaza sin llamar al servidor", async () => {
    const f = vi.fn();
    const auth = crearAuthLocal({ fetch: f as never, almacen: almacenEnMemoria() });
    for (const malo of ["12345", "abcdef", "1234567", ""]) {
      const error = await auth.confirmarTotp(malo).catch((e) => e);
      expect(error.codigo).toBe("CODIGO_INVALIDO");
    }
    expect(f).not.toHaveBeenCalled();
  });

  it("un token vencido no cuenta como sesión", async () => {
    const almacen = almacenEnMemoria();
    almacen.setItem("cc-local-token", tokenConExp(Math.floor(Date.now() / 1000) - 10));
    const auth = crearAuthLocal({ almacen });
    expect(await auth.haySesion()).toBe(false);
    expect(await auth.token()).toBeNull();
  });

  it("si el stack no responde, avisa sin exponer detalles", async () => {
    const f = vi.fn().mockResolvedValue(new Response("<html>", { status: 502 }));
    const auth = crearAuthLocal({ fetch: f as never, almacen: almacenEnMemoria() });
    const error = await auth.iniciarSesion("a@b.test", "x").catch((e) => e);
    expect(error.codigo).toBe("DESCONOCIDO");
  });

  it("el registro y el restablecimiento no existen en local; la recuperación no revela nada", async () => {
    const auth = crearAuthLocal({ almacen: almacenEnMemoria() });
    await expect(auth.solicitarRecuperacion("a@b.test")).resolves.toBeUndefined();
    await expect(auth.restablecerContrasena("a@b.test", "1", "x")).rejects.toBeInstanceOf(ErrorAcceso);
    await expect(
      auth.registrar({ nombre: "n", correo: "a@b.test", contrasena: "x", codigoInvitacion: "c" }),
    ).rejects.toBeInstanceOf(ErrorAcceso);
  });
});
