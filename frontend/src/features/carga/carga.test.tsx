import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { json, problema, simularRutas, type Llamada } from "@/test/fixturas220";
import type { Carga, CargaDetalle } from "./api";
import { RutasCarga } from "./RutasCarga";
import { esperarAccesible } from "@/test/axe";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
let clics: string[];

beforeEach(() => {
  clics = [];
  URL.createObjectURL = vi.fn(() => "blob:prueba");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clics.push(this.download);
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const montar = (ruta = "/cargas") =>
  renderizar(
    <Routes>
      <Route path="cargas/*" element={<RutasCarga />} />
    </Routes>,
    { ruta },
  );

function carga(sobre: Partial<Carga> = {}): Carga {
  return {
    id: 5,
    nombre_archivo: "empleados.xlsx",
    estado: "TERMINADA",
    confirmada: true,
    fecha_carga: "2026-11-13T15:42:00Z",
    fecha_fin: "2026-11-13T15:43:00Z",
    filas_ok: 98,
    filas_error: 2,
    total_filas: 100,
    motivo_cierre: null,
    version_plantilla: "3",
    ...sobre,
  };
}

const detalle = (c: Carga, items: CargaDetalle["filas"]["items"] = [], total = items.length): CargaDetalle => ({
  carga: c,
  filas: { items, pagina: 1, limite: 20, total },
});

const FILA_ERROR = {
  numero_fila: 7,
  resultado: "ERROR" as const,
  errores: [{ codigo: "CELULAR_INVALIDO", mensaje: "El celular debe tener 10 dígitos." }],
};

const archivo = (nombre = "empleados.xlsx", tamano = 10) => {
  const f = new File([new Uint8Array(tamano)], nombre, { type: XLSX });
  return f;
};

describe("carga masiva: plantilla y subida", () => {
  it("descarga la plantilla con el token en el encabezado (no en la URL)", async () => {
    const llamadas = simularRutas((url) => {
      if (url.pathname === "/api/v1/cargas/plantilla") return new Response("xlsx", { status: 200, headers: { "Content-Type": XLSX } });
      if (url.pathname === "/api/v1/cargas") return json({ items: [], pagina: 1, limite: 10, total: 0 });
      return undefined;
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Descargar plantilla" }));
    await waitFor(() => expect(clics).toEqual(["plantilla_colaboradores.xlsx"]));
    const peticion = llamadas.find((l) => l.url === "/api/v1/cargas/plantilla")!;
    expect((peticion.init!.headers as Record<string, string>).Authorization).toBe("Bearer token-de-prueba");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("valida extensión y tamaño antes de subir", async () => {
    const llamadas = simularRutas((url) => (url.pathname === "/api/v1/cargas" ? json({ items: [], pagina: 1, limite: 10, total: 0 }) : undefined));
    const u = userEvent.setup({ applyAccept: false });
    montar();
    const campo = await screen.findByLabelText("Archivo de carga");
    await u.upload(campo, new File(["x"], "datos.pdf", { type: "application/pdf" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El archivo debe ser de Excel (.xlsx).");

    const grande = archivo("grande.xlsx", 10);
    Object.defineProperty(grande, "size", { value: 6 * 1024 * 1024 });
    await u.upload(campo, grande);
    expect(await screen.findByText("El archivo no puede pesar más de 5 MB.")).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Subir y validar" }));
    expect(await screen.findByText("Elige un archivo.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST")).toBe(false);
  });

  it("sube con URL firmada: inicia, PUT directo a S3 sin credenciales, confirma y abre el seguimiento", async () => {
    const llamadas = simularRutas((url, metodo) => {
      if (url.host === "s3.local" && metodo === "PUT") return new Response(null, { status: 200 });
      if (url.pathname === "/api/v1/cargas" && metodo === "POST")
        return json(
          { carga_id: 5, url_subida: "https://s3.local/bucket/cargas/5.xlsx?firma=abc", s3_key: "cargas/5.xlsx", expira: "2026-11-13T16:00:00Z", content_type: XLSX },
          201,
        );
      if (url.pathname === "/api/v1/cargas/5/confirmar") return json(carga({ estado: "EN_PROCESO", filas_ok: 0, filas_error: 0, total_filas: null }), 202);
      if (url.pathname === "/api/v1/cargas/5") return json(detalle(carga({ estado: "EN_PROCESO", filas_ok: 10, filas_error: 0, total_filas: 100 })));
      if (url.pathname === "/api/v1/cargas") return json({ items: [], pagina: 1, limite: 10, total: 0 });
      return undefined;
    });
    const u = userEvent.setup();
    montar();
    const f = archivo("empleados.xlsx", 2048);
    await u.upload(await screen.findByLabelText("Archivo de carga"), f);
    await u.click(screen.getByRole("button", { name: "Subir y validar" }));

    expect(await screen.findByRole("heading", { name: "Carga #5" })).toBeInTheDocument();
    const escrituras = llamadas.filter((l) => l.metodo !== "GET");
    expect(escrituras.map((l) => `${l.metodo} ${l.url.split("?")[0]}`)).toEqual([
      "POST /api/v1/cargas",
      "PUT /bucket/cargas/5.xlsx",
      "POST /api/v1/cargas/5/confirmar",
    ]);
    expect(escrituras[0]!.cuerpo).toEqual({ nombre_archivo: "empleados.xlsx", tamano: 2048 });
    const put = escrituras[1]!;
    expect(put.init!.body).toBe(f);
    const cabeceras = put.init!.headers as Record<string, string>;
    expect(cabeceras["Content-Type"]).toBe(XLSX);
    expect(cabeceras.Authorization).toBeUndefined();
  });

  it("si el archivo no corresponde a la plantilla (422) se informa el motivo", async () => {
    simularRutas((url, metodo) => {
      if (url.host === "s3.local") return new Response(null, { status: 200 });
      if (url.pathname === "/api/v1/cargas" && metodo === "POST")
        return json({ carga_id: 6, url_subida: "https://s3.local/b/6.xlsx", s3_key: "6", expira: "2026-11-13T16:00:00Z", content_type: XLSX }, 201);
      if (url.pathname === "/api/v1/cargas/6/confirmar") return problema(422, "CARGA_ARCHIVO_INVALIDO", "El archivo no corresponde a la plantilla vigente.");
      if (url.pathname === "/api/v1/cargas") return json({ items: [], pagina: 1, limite: 10, total: 0 });
      return undefined;
    });
    const u = userEvent.setup();
    montar();
    await u.upload(await screen.findByLabelText("Archivo de carga"), archivo());
    await u.click(screen.getByRole("button", { name: "Subir y validar" }));
    expect(await screen.findByText("El archivo no corresponde a la plantilla vigente.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Carga masiva de colaboradores" })).toBeInTheDocument();
  });

  it("lista las cargas anteriores con su estado", async () => {
    simularRutas((url) =>
      url.pathname === "/api/v1/cargas"
        ? json({ items: [carga(), carga({ id: 4, estado: "CANCELADA", nombre_archivo: "viejo.xlsx", filas_ok: 0, filas_error: 0 })], pagina: 1, limite: 10, total: 2 })
        : undefined,
    );
    montar();
    expect(await screen.findByText("empleados.xlsx")).toBeInTheDocument();
    expect(screen.getByText("Terminada")).toHaveClass("ok");
    expect(screen.getByText("Cancelada")).toHaveClass("neutro");
    expect(screen.getByRole("link", { name: "Ver carga 5" })).toHaveAttribute("href", "/cargas/5");
  });
});

describe("carga masiva: seguimiento, resumen y reporte", () => {
  it("sondea mientras está en proceso y muestra el resumen al terminar", async () => {
    let consultas = 0;
    simularRutas((url) => {
      if (url.pathname === "/api/v1/cargas/5") {
        consultas += 1;
        return json(consultas === 1 ? detalle(carga({ estado: "EN_PROCESO", filas_ok: 30, filas_error: 0, total_filas: 100 })) : detalle(carga(), [FILA_ERROR], 1));
      }
      return undefined;
    });
    montar("/cargas/5");

    expect(await screen.findByText("30 de 100 filas procesadas")).toBeInTheDocument();
    expect(screen.getByText("En proceso")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar carga" })).toBeInTheDocument();

    // El siguiente sondeo trae la carga terminada.
    await waitFor(() => expect(screen.getByText("Terminada")).toBeInTheDocument(), { timeout: 5000 });
    const resumen = screen.getByRole("region", { name: "Resumen" });
    expect(within(resumen).getByText("100")).toBeInTheDocument();
    expect(within(resumen).getByText("98")).toBeInTheDocument();
    expect(within(resumen).getByText("2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar carga" })).not.toBeInTheDocument();
    expect(screen.getByText("El celular debe tener 10 dígitos.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descargar reporte de errores" })).toBeInTheDocument();
    const antes = consultas;
    await new Promise((r) => setTimeout(r, 1800));
    expect(consultas).toBe(antes); // ya no sondea
  }, 15000);

  it("descarga el reporte de errores en CSV con el token en el encabezado", async () => {
    const llamadas = simularRutas((url) => {
      if (url.pathname === "/api/v1/cargas/5/errores") return new Response("fila,codigo\n7,CELULAR_INVALIDO", { status: 200, headers: { "Content-Type": "text/csv" } });
      if (url.pathname === "/api/v1/cargas/5") return json(detalle(carga(), [FILA_ERROR], 1));
      return undefined;
    });
    const u = userEvent.setup();
    montar("/cargas/5");
    await u.click(await screen.findByRole("button", { name: "Descargar reporte de errores" }));
    await waitFor(() => expect(clics).toEqual(["errores_carga_5.csv"]));
    const p = llamadas.find((l) => l.url === "/api/v1/cargas/5/errores")!;
    expect((p.init!.headers as Record<string, string>).Authorization).toBe("Bearer token-de-prueba");
  });

  it("sin filas con error no ofrece el reporte", async () => {
    simularRutas((url) => (url.pathname === "/api/v1/cargas/5" ? json(detalle(carga({ filas_ok: 100, filas_error: 0 }))) : undefined));
    montar("/cargas/5");
    await screen.findByText("Terminada");
    expect(screen.queryByRole("button", { name: "Descargar reporte de errores" })).not.toBeInTheDocument();
  });

  it("filtra las filas por resultado", async () => {
    const llamadas: Llamada[] = simularRutas((url) => (url.pathname === "/api/v1/cargas/5" ? json(detalle(carga(), [FILA_ERROR], 1)) : undefined));
    const u = userEvent.setup();
    montar("/cargas/5");
    await screen.findByText("Terminada");
    await u.selectOptions(screen.getByLabelText("Filtrar por resultado"), "ERROR");
    await waitFor(() => expect(llamadas.at(-1)!.url).toContain("resultado=ERROR"));
    expect(llamadas.at(-1)!.url).toContain("pagina=1");
  });

  it("cancela una carga en proceso", async () => {
    const llamadas = simularRutas((url, metodo) => {
      if (url.pathname === "/api/v1/cargas/5/cancelar" && metodo === "POST") return json(carga({ estado: "CANCELADA" }));
      if (url.pathname === "/api/v1/cargas/5") return json(detalle(carga({ estado: "EN_PROCESO", filas_ok: 5, filas_error: 0, total_filas: 100 })));
      return undefined;
    });
    const u = userEvent.setup();
    montar("/cargas/5");
    await u.click(await screen.findByRole("button", { name: "Cancelar carga" }));
    await waitFor(() => expect(llamadas.some((l) => l.url === "/api/v1/cargas/5/cancelar" && l.metodo === "POST")).toBe(true));
  });

  it("una carga cancelada muestra el motivo", async () => {
    simularRutas((url) =>
      url.pathname === "/api/v1/cargas/5" ? json(detalle(carga({ estado: "CANCELADA", motivo_cierre: "NO_CONFIRMADA", filas_ok: 0, filas_error: 0, total_filas: null }))) : undefined,
    );
    montar("/cargas/5");
    expect(await screen.findByText("Carga cancelada: el archivo no se confirmó en 1 hora.")).toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("la carga masiva (listado) no tiene violaciones críticas ni serias de axe", async () => {
    simularRutas((url) =>
      url.pathname === "/api/v1/cargas"
        ? json({ items: [carga(), carga({ id: 4, estado: "CANCELADA", nombre_archivo: "viejo.xlsx", filas_ok: 0, filas_error: 0 })], pagina: 1, limite: 10, total: 2 })
        : undefined,
    );
    const { container } = montar();
    await screen.findByText("empleados.xlsx");
    await esperarAccesible(container);
  });

  it("el seguimiento de una carga con filas con error no tiene violaciones críticas ni serias de axe", async () => {
    simularRutas((url) => (url.pathname === "/api/v1/cargas/5" ? json(detalle(carga(), [FILA_ERROR], 1)) : undefined));
    const { container } = montar("/cargas/5");
    await screen.findByText("El celular debe tener 10 dígitos.");
    await esperarAccesible(container);
  });
});
