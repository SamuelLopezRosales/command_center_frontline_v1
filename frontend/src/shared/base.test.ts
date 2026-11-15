import { describe, expect, it, vi } from "vitest";
import { ErrorApi, aplicarErroresDeCampo, leerProblema } from "./errores";
import { fechaCivil, fechaHora } from "./fechas";
import { construirUrl } from "@/api-client/http";
import { CABECERAS_DESARROLLO } from "../../cabeceras";

describe("errores problem+json", () => {
  it("lee el problema y expone los errores por campo", async () => {
    const r = new Response(
      JSON.stringify({
        title: "Datos no válidos",
        status: 422,
        codigo: "VALIDACION",
        correlacion_id: "abc",
        errores: [{ campo: "rfc", codigo: "FORMATO_INVALIDO", mensaje: "RFC inválido." }],
      }),
      { status: 422 },
    );
    const e = await leerProblema(r);
    expect(e).toBeInstanceOf(ErrorApi);
    expect(e.porCampo().get("rfc")).toBe("RFC inválido.");
    expect(e.correlacionId).toBe("abc");
  });

  it("un cuerpo que no es JSON da un error genérico", async () => {
    const e = await leerProblema(new Response("<html>", { status: 502 }));
    expect(e.status).toBe(502);
    expect(e.message).toMatch(/No se pudo/);
  });

  it("aplica los errores a los campos del formulario", () => {
    const setError = vi.fn();
    const e = new ErrorApi({ title: "x", status: 422, codigo: "V", errores: [{ campo: "correo", codigo: "C", mensaje: "Ya existe." }] });
    expect(aplicarErroresDeCampo(e, setError)).toBe(true);
    expect(setError).toHaveBeenCalledWith("correo", { type: "C", message: "Ya existe." });
    expect(aplicarErroresDeCampo(new Error("otro"), setError)).toBe(false);
  });
});

describe("fechas en America/Mexico_City", () => {
  it("una hora UTC de madrugada cae en el día anterior de México", () => {
    // 2026-11-14 03:30 UTC = 13 nov 21:30 en la Ciudad de México (UTC-6).
    expect(fechaHora("2026-11-14T03:30:00Z")).toBe("13 nov, 21:30");
  });
  it("una fecha civil no se desplaza", () => {
    expect(fechaCivil("2026-11-13")).toBe("13/11/2026");
  });
});

describe("cliente", () => {
  it("omite parámetros vacíos al construir la URL", () => {
    expect(construirUrl("/api/v1/x", { q: "ana", pagina: 2, vacio: "", nulo: null, no: undefined })).toBe("/api/v1/x?q=ana&pagina=2");
  });
});

describe("cabeceras de desarrollo", () => {
  it("la CSP solo permite recursos propios", () => {
    const csp = CABECERAS_DESARROLLO["Content-Security-Policy"];
    expect(csp).toContain("default-src 'self'");
    expect(csp).not.toMatch(/https?:\/\/(?!localhost)/);
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
  });
});
