import { describe, expect, it, vi } from "vitest";
import { cargarConfig, RUTA_CONFIG, validarConfig } from "./config";

const respuestaJson = (cuerpo: unknown, tipo = "application/json") =>
  new Response(JSON.stringify(cuerpo), { status: 200, headers: { "content-type": tipo } });

describe("configuración de ejecución", () => {
  it("lee /config.json sin usar la caché y devuelve los identificadores", async () => {
    const cargador = vi.fn().mockResolvedValue(
      respuestaJson({
        userPoolId: "us-east-1_abc",
        userPoolClientId: "cliente",
        region: "us-east-1",
        apiBaseUrl: "https://d1.cloudfront.net",
        registroAbierto: true,
      }),
    );
    const c = await cargarConfig(cargador, {});
    expect(cargador).toHaveBeenCalledWith(RUTA_CONFIG, expect.objectContaining({ cache: "no-store" }));
    expect(c).toEqual({
      userPoolId: "us-east-1_abc",
      userPoolClientId: "cliente",
      region: "us-east-1",
      apiBaseUrl: "https://d1.cloudfront.net",
      registroAbierto: true,
    });
  });

  it("sin archivo usa las variables de compilación", async () => {
    const cargador = vi.fn().mockResolvedValue(new Response("no", { status: 404 }));
    const c = await cargarConfig(cargador, {
      VITE_COGNITO_USER_POOL_ID: "us-east-1_dev",
      VITE_COGNITO_CLIENT_ID: "dev",
    });
    expect(c.userPoolId).toBe("us-east-1_dev");
    expect(c.apiBaseUrl).toBe("");
    expect(c.registroAbierto).toBe(false); // sin archivo, el registro exige invitación
  });

  it("una respuesta HTML (servidor de desarrollo) no se toma como configuración", async () => {
    const cargador = vi.fn().mockResolvedValue(new Response("<html>", { status: 200, headers: { "content-type": "text/html" } }));
    await expect(cargarConfig(cargador, {})).rejects.toThrow(/userPoolId/);
  });

  it("un fallo de red sin variables de compilación da un error claro", async () => {
    const cargador = vi.fn().mockRejectedValue(new Error("red"));
    await expect(cargarConfig(cargador, {})).rejects.toThrow(/userPoolId/);
  });

  it("rechaza una configuración incompleta", () => {
    expect(() => validarConfig({ userPoolId: "x" })).toThrow();
    expect(() => validarConfig(null)).toThrow();
  });
});
