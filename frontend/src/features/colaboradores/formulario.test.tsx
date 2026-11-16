import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { DINAMICOS, FIJOS, ORGS, PLANTAS, detalle, fila, json, listadoCampos, problema, simularRutas, type Llamada } from "@/test/fixturas220";
import type { ColaboradorDetalle } from "./api";
import { RutasColaboradores } from "./RutasColaboradores";
import { esperarAccesible } from "@/test/axe";

afterEach(() => vi.unstubAllGlobals());

interface Opciones {
  detalle?: ColaboradorDetalle;
  etag?: string;
  /** Respuestas a los verbos de escritura sobre el colaborador 7 y a la creación. */
  escritura?: (ruta: string, metodo: string, cuerpo: any) => Response | undefined; // eslint-disable-line @typescript-eslint/no-explicit-any
}

function api(o: Opciones = {}) {
  const d = o.detalle ?? detalle();
  return simularRutas((url, metodo, init) => {
    const p = url.pathname;
    if (p === "/api/v1/organizaciones") return json({ items: ORGS });
    if (p === "/api/v1/plantas") return json({ items: PLANTAS });
    if (p === "/api/v1/campos") return json(listadoCampos(DINAMICOS));
    if (p === "/api/v1/colaboradores" && metodo === "GET") return json({ items: [fila(1)], pagina: 1, limite: 10, total: 1 });
    const cuerpo = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    const propio = o.escritura?.(p, metodo, cuerpo);
    if (propio) return propio;
    if (p === "/api/v1/colaboradores/7" && metodo === "GET") return json(d, 200, { ETag: o.etag ?? '"v1"' });
    if (p.startsWith("/api/v1/colaboradores")) return json(d);
    return undefined;
  });
}

const montar = (ruta: string) =>
  renderizar(
    <Routes>
      <Route path="colaboradores/*" element={<RutasColaboradores />} />
    </Routes>,
    { ruta },
  );

const peticion = (llamadas: Llamada[], metodo: string, fin = "") => llamadas.find((l) => l.metodo === metodo && l.url.endsWith(fin) && !l.url.includes("/campos") && !l.url.includes("/plantas"));

async function llenarFijos(u: ReturnType<typeof userEvent.setup>) {
  await u.type(await screen.findByLabelText("Número de empleado"), "emp-0100");
  await u.type(screen.getByLabelText("Nombre(s)"), "Valeria");
  await u.type(screen.getByLabelText("Apellido paterno"), "Núñez");
  await u.type(screen.getByLabelText("Apellido materno"), "Ortega");
  await u.type(screen.getByLabelText("Celular con WhatsApp"), "55 1234 5678");
  await screen.findByRole("option", { name: "ORG01 · Empresa Grupo Industrial Norte" });
  await u.selectOptions(screen.getByLabelText("Organización"), "1");
  await u.selectOptions(screen.getByLabelText("Planta o centro de trabajo"), "2");
  await u.type(screen.getByLabelText("Fecha de ingreso"), "2026-02-01");
  await u.type(screen.getByLabelText("Puesto"), "Diseñadora UX");
  await u.selectOptions(screen.getByLabelText("Tipo de empleado"), "ADMINISTRATIVO");
}

describe("formulario de alta (cv1_03)", () => {
  it("se genera desde la configuración: los once fijos obligatorios y los campos activos", async () => {
    api();
    montar("/colaboradores/nuevo");
    expect(await screen.findByRole("heading", { name: "Nuevo colaborador" })).toBeInTheDocument();
    await screen.findByLabelText("Número de empleado");

    // Los once campos fijos, en el orden de la configuración.
    for (const f of FIJOS) expect(screen.getByLabelText(f.nombre)).toBeInTheDocument();
    for (const f of FIJOS.filter((x) => x.clave !== "estatus")) expect(screen.getByLabelText(f.nombre)).toHaveAttribute("aria-required", "true");
    expect(screen.getByLabelText("Estatus")).toHaveValue("ACTIVO");
    expect(screen.getByLabelText("Estatus")).toBeDisabled();

    // Campos adicionales: solo los activos (Ruta de transporte está inactivo).
    expect(screen.getByLabelText("Área")).toBeInTheDocument();
    expect(screen.getByLabelText("Turno")).toBeInTheDocument();
    expect(screen.getByLabelText("Sueldo (MXN)")).toBeInTheDocument();
    expect(screen.getByLabelText("NSS")).toBeInTheDocument();
    expect(screen.getByLabelText("Bono de productividad")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ruta de transporte")).not.toBeInTheDocument();
    expect(within(screen.getByLabelText("Área")).getByRole("option", { name: "Producción" })).toBeInTheDocument();
    // Un campo adicional obligatorio también se marca como requerido.
    expect(screen.getByLabelText("NSS")).toHaveAttribute("aria-required", "true");
    expect(screen.getByLabelText("Sueldo (MXN)")).not.toHaveAttribute("aria-required");
  });

  it("marca los campos sensibles y muestra la casilla de consentimiento", async () => {
    api();
    montar("/colaboradores/nuevo");
    await screen.findByLabelText("Sueldo (MXN)");
    // Sueldo, NSS y Bono son sensibles; Área no.
    expect(screen.getAllByText("Sensible")).toHaveLength(3);
    const sueldo = screen.getByLabelText("Sueldo (MXN)").closest(".col-control") as HTMLElement;
    expect(within(sueldo).getByText("Sensible")).toBeInTheDocument();
    const area = screen.getByLabelText("Área").closest(".col-control") as HTMLElement;
    expect(within(area).queryByText("Sensible")).not.toBeInTheDocument();

    const casilla = screen.getByRole("checkbox", { name: "El colaborador dio su consentimiento para recibir constancias por WhatsApp" });
    expect(casilla).not.toBeChecked();
    expect(screen.getByText("Sin consentimiento vigente el colaborador no puede solicitar constancias.")).toBeInTheDocument();
  });

  it("no envía con campos obligatorios vacíos y marca error en cada uno", async () => {
    const llamadas = api();
    const u = userEvent.setup();
    montar("/colaboradores/nuevo");
    await screen.findByLabelText("Número de empleado");
    await u.click(screen.getByRole("button", { name: "Guardar colaborador" }));
    // 10 fijos editables + NSS (obligatorio configurado).
    await waitFor(() => expect(screen.getAllByText("Este campo es obligatorio.")).toHaveLength(11));
    expect(screen.getByLabelText("Número de empleado")).toHaveAttribute("aria-invalid", "true");
    expect(llamadas.some((l) => l.metodo === "POST")).toBe(false);
  });

  it("valida el celular de 10 dígitos antes de enviar", async () => {
    api();
    const u = userEvent.setup();
    montar("/colaboradores/nuevo");
    await u.type(await screen.findByLabelText("Celular con WhatsApp"), "5512");
    await u.click(screen.getByRole("button", { name: "Guardar colaborador" }));
    expect(await screen.findByText("El celular debe tener 10 dígitos.")).toBeInTheDocument();
  });

  it("crea el colaborador: celular solo en el cuerpo, número en mayúsculas, valores tipados y consentimiento", async () => {
    const llamadas = api({ escritura: (p, m) => (p === "/api/v1/colaboradores" && m === "POST" ? json(detalle({ id: 99 }), 201) : undefined) });
    const u = userEvent.setup();
    montar("/colaboradores/nuevo");
    await llenarFijos(u);
    await u.selectOptions(screen.getByLabelText("Área"), "ALMACEN");
    await u.type(screen.getByLabelText("NSS"), "12345678901");
    await u.type(screen.getByLabelText("Sueldo (MXN)"), "9500");
    await u.click(screen.getByRole("checkbox", { name: /consentimiento/ }));
    await u.click(screen.getByRole("button", { name: "Guardar colaborador" }));

    await waitFor(() => expect(peticion(llamadas, "POST")).toBeDefined());
    const post = peticion(llamadas, "POST")!;
    expect(post.url).toBe("/api/v1/colaboradores");
    expect(post.cuerpo).toEqual({
      numero_empleado: "EMP-0100",
      nombres: "Valeria",
      apellido_paterno: "Núñez",
      apellido_materno: "Ortega",
      celular: "5512345678",
      organizacion_id: 1,
      planta_id: 2,
      fecha_ingreso: "2026-02-01",
      puesto: "Diseñadora UX",
      tipo_empleado: "ADMINISTRATIVO",
      campos: { "CAMP-0001": "ALMACEN", "CAMP-0008": "12345678901", "CAMP-0005": 9500 },
      consentimiento: true,
    });
    // Ninguna URL lleva datos personales.
    expect(llamadas.every((l) => !l.url.includes("5512345678") && !l.url.includes("12345678901"))).toBe(true);
    // Tras crear vuelve al listado.
    expect(await screen.findByRole("heading", { name: "Colaboradores" })).toBeInTheDocument();
  });

  it("sin marcar la casilla se guarda con consentimiento falso", async () => {
    const llamadas = api({ escritura: (p, m) => (p === "/api/v1/colaboradores" && m === "POST" ? json(detalle(), 201) : undefined) });
    const u = userEvent.setup();
    montar("/colaboradores/nuevo");
    await llenarFijos(u);
    await u.type(screen.getByLabelText("NSS"), "12345678901");
    await u.click(screen.getByRole("button", { name: "Guardar colaborador" }));
    await waitFor(() => expect(peticion(llamadas, "POST")).toBeDefined());
    expect(peticion(llamadas, "POST")!.cuerpo.consentimiento).toBe(false);
  });

  it("muestra los errores por campo que devuelve el servidor", async () => {
    api({
      escritura: (p, m) =>
        p === "/api/v1/colaboradores" && m === "POST"
          ? problema(422, "VALIDACION", "Hay datos inválidos.", {
              errores: [
                { campo: "celular", codigo: "FORMATO", mensaje: "El celular no es válido." },
                { campo: "organizacion_id", codigo: "NO_EXISTE", mensaje: "La organización no existe." },
                { campo: "campos.CAMP-0008", codigo: "FORMATO", mensaje: "El NSS debe tener 11 dígitos." },
              ],
            })
          : undefined,
    });
    const u = userEvent.setup();
    montar("/colaboradores/nuevo");
    await llenarFijos(u);
    await u.type(screen.getByLabelText("NSS"), "123");
    await u.click(screen.getByRole("button", { name: "Guardar colaborador" }));

    expect(await screen.findByText("El celular no es válido.")).toBeInTheDocument();
    expect(screen.getByText("La organización no existe.")).toBeInTheDocument();
    expect(screen.getByText("El NSS debe tener 11 dígitos.")).toBeInTheDocument();
    expect(screen.getByLabelText("Celular con WhatsApp")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("NSS")).toHaveAttribute("aria-invalid", "true");
  });

  it("un número de empleado duplicado (409) se marca en su campo", async () => {
    api({
      escritura: (p, m) =>
        p === "/api/v1/colaboradores" && m === "POST"
          ? problema(409, "NUMERO_EMPLEADO_DUPLICADO", "Ya existe un colaborador con ese número de empleado.")
          : undefined,
    });
    const u = userEvent.setup();
    montar("/colaboradores/nuevo");
    await llenarFijos(u);
    await u.type(screen.getByLabelText("NSS"), "12345678901");
    await u.click(screen.getByRole("button", { name: "Guardar colaborador" }));
    expect(await screen.findByText("Ya existe un colaborador con ese número de empleado.")).toBeInTheDocument();
    expect(screen.getByLabelText("Número de empleado")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("edición, baja y reactivación", () => {
  it("carga el colaborador, deja el número de solo lectura y no muestra valores sensibles", async () => {
    api();
    montar("/colaboradores/7");
    expect(await screen.findByRole("heading", { name: "Editar colaborador" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Nombre(s)")).toHaveValue("Ricardo");
    expect(screen.getByLabelText("Número de empleado")).toHaveValue("EMP-0007");
    expect(screen.getByLabelText("Número de empleado")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Puesto")).toHaveValue("Supervisor de Almacén");
    expect(screen.getByLabelText("Área")).toHaveValue("ALMACEN");
    // El celular y los sensibles llegan enmascarados: el campo queda vacío.
    expect(screen.getByLabelText("Celular con WhatsApp")).toHaveValue("");
    expect(screen.getByText("Guardado: ******5678. Escribe para reemplazarlo.")).toBeInTheDocument();
    expect(screen.getByLabelText("NSS")).toHaveValue("");
    expect(screen.getAllByText("Valor guardado (oculto). Escribe para reemplazarlo.").length).toBe(2);
    // Un sensible obligatorio ya guardado no se vuelve a exigir.
    expect(screen.getByLabelText("NSS")).not.toHaveAttribute("aria-required");
    expect(screen.getByRole("checkbox", { name: /consentimiento/ })).toBeChecked();
  });

  it("guarda con If-Match y solo envía los campos modificados", async () => {
    const llamadas = api({ etag: '"v7"', escritura: (p, m) => (p === "/api/v1/colaboradores/7" && m === "PATCH" ? json(detalle({ puesto: "Jefe de Almacén" })) : undefined) });
    const u = userEvent.setup();
    montar("/colaboradores/7");
    const puesto = await screen.findByLabelText("Puesto");
    await u.clear(puesto);
    await u.type(puesto, "Jefe de Almacén");
    await u.click(screen.getByRole("button", { name: "Guardar cambios" }));

    await waitFor(() => expect(peticion(llamadas, "PATCH")).toBeDefined());
    const patch = peticion(llamadas, "PATCH")!;
    expect(patch.cuerpo).toEqual({ puesto: "Jefe de Almacén" });
    expect((patch.init!.headers as Record<string, string>)["If-Match"]).toBe('"v7"');
    expect(await screen.findByText("Cambios guardados.")).toBeInTheDocument();
  });

  it("para reemplazar un sensible hay que escribirlo; el celular se envía solo en el cuerpo", async () => {
    const llamadas = api({ escritura: (p, m) => (p === "/api/v1/colaboradores/7" && m === "PATCH" ? json(detalle()) : undefined) });
    const u = userEvent.setup();
    montar("/colaboradores/7");
    await u.type(await screen.findByLabelText("NSS"), "98765432109");
    await u.type(screen.getByLabelText("Celular con WhatsApp"), "8112345678");
    await u.click(screen.getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() => expect(peticion(llamadas, "PATCH")).toBeDefined());
    expect(peticion(llamadas, "PATCH")!.cuerpo).toEqual({ celular: "8112345678", campos: { "CAMP-0008": "98765432109" } });
    expect(llamadas.every((l) => !l.url.includes("8112345678") && !l.url.includes("98765432109"))).toBe(true);
  });

  it("sin cambios no llama a la API de escritura", async () => {
    const llamadas = api();
    const u = userEvent.setup();
    montar("/colaboradores/7");
    await screen.findByLabelText("Puesto");
    await u.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(await screen.findByText("No hay cambios que guardar.")).toBeInTheDocument();
    expect(peticion(llamadas, "PATCH")).toBeUndefined();
  });

  it("un 412 por versión desactualizada se informa al usuario", async () => {
    api({ escritura: (p, m) => (p === "/api/v1/colaboradores/7" && m === "PATCH" ? problema(412, "VERSION_DESACTUALIZADA", "El colaborador cambió; recarga la página.") : undefined) });
    const u = userEvent.setup();
    montar("/colaboradores/7");
    const puesto = await screen.findByLabelText("Puesto");
    await u.type(puesto, " B");
    await u.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El colaborador cambió; recarga la página.");
  });

  it("cambiar el consentimiento llama a la API de consentimiento", async () => {
    const llamadas = api({ escritura: (p, m) => (p === "/api/v1/colaboradores/7/consentimiento" && m === "PUT" ? json(detalle()) : undefined) });
    const u = userEvent.setup();
    montar("/colaboradores/7");
    await u.click(await screen.findByRole("checkbox", { name: /consentimiento/ }));
    await u.click(screen.getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() => expect(peticion(llamadas, "PUT")).toBeDefined());
    expect(peticion(llamadas, "PUT")!.cuerpo).toEqual({ otorgado: false });
    expect(peticion(llamadas, "PATCH")).toBeUndefined();
  });

  it("baja: pide la fecha, la envía y no borra al colaborador", async () => {
    const llamadas = api({
      escritura: (p, m) => (p === "/api/v1/colaboradores/7/baja" && m === "POST" ? json(detalle({ estatus: "BAJA", fecha_baja: "2026-11-14" })) : undefined),
    });
    const u = userEvent.setup();
    montar("/colaboradores/7");
    await u.click(await screen.findByRole("button", { name: "Dar de baja" }));
    await u.click(screen.getByRole("button", { name: "Confirmar baja" }));
    expect(await screen.findByText("Indica la fecha de baja.")).toBeInTheDocument();
    expect(peticion(llamadas, "POST", "/baja")).toBeUndefined();

    await u.type(screen.getByLabelText("Fecha de baja"), "2026-11-14");
    await u.click(screen.getByRole("button", { name: "Confirmar baja" }));
    await waitFor(() => expect(peticion(llamadas, "POST", "/baja")).toBeDefined());
    expect(peticion(llamadas, "POST", "/baja")!.cuerpo).toEqual({ fecha_baja: "2026-11-14" });
    expect(llamadas.some((l) => l.metodo === "DELETE")).toBe(false);
  });

  it("reactivar con consentimiento vigente lo hace directamente", async () => {
    const baja = detalle({ estatus: "BAJA", fecha_baja: "2026-10-01" });
    const llamadas = api({
      detalle: baja,
      escritura: (p, m) => (p === "/api/v1/colaboradores/7/reactivar" && m === "POST" ? json(detalle()) : undefined),
    });
    const u = userEvent.setup();
    montar("/colaboradores/7");
    expect(await screen.findByText("En baja desde 01/10/2026")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Reactivar" }));
    await waitFor(() => expect(peticion(llamadas, "POST", "/reactivar")).toBeDefined());
    expect(peticion(llamadas, "POST", "/reactivar")!.cuerpo).toEqual({ consentimiento: false });
  });

  it("reactivar sin consentimiento vigente exige confirmarlo", async () => {
    const baja = detalle({ estatus: "BAJA", fecha_baja: "2026-10-01", consentimiento: { otorgado: false, vigente: false, fecha: null, vigente_hasta: null } });
    const llamadas = api({
      detalle: baja,
      escritura: (p, m, cuerpo) =>
        p === "/api/v1/colaboradores/7/reactivar" && m === "POST"
          ? cuerpo.consentimiento
            ? json(detalle())
            : problema(422, "CONSENTIMIENTO_REQUERIDO", "Se requiere consentimiento para reactivar.")
          : undefined,
    });
    const u = userEvent.setup();
    montar("/colaboradores/7");
    await u.click(await screen.findByRole("button", { name: "Reactivar" }));
    expect(screen.getByText(/no tiene consentimiento vigente/)).toBeInTheDocument();
    expect(peticion(llamadas, "POST", "/reactivar")).toBeUndefined();

    await u.click(screen.getByRole("button", { name: "Confirmar reactivación" }));
    expect(await screen.findByText("Se requiere consentimiento para reactivar.")).toBeInTheDocument();

    await u.click(screen.getByRole("checkbox", { name: "El colaborador otorgó su consentimiento" }));
    await u.click(screen.getByRole("button", { name: "Confirmar reactivación" }));
    await waitFor(() => expect(llamadas.filter((l) => l.url.endsWith("/reactivar")).at(-1)?.cuerpo).toEqual({ consentimiento: true }));
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el formulario de alta no tiene violaciones críticas ni serias de axe", async () => {
    api();
    const { container } = montar("/colaboradores/nuevo");
    await screen.findByLabelText("Número de empleado");
    await screen.findByLabelText("Área");
    await esperarAccesible(container);
  });
});
