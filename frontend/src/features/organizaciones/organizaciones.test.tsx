import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { ORGS, PLANTAS, json, problema, simularRutas } from "@/test/fixturas220";
import { RutasOrganizaciones } from "./RutasOrganizaciones";
import { esperarAccesible } from "@/test/axe";

afterEach(() => vi.unstubAllGlobals());

const montar = (ruta = "/organizaciones") =>
  renderizar(
    <Routes>
      <Route path="organizaciones/*" element={<RutasOrganizaciones />} />
    </Routes>,
    { ruta },
  );

describe("organizaciones", () => {
  it("lista las organizaciones con su logotipo y estado, y enlaza a plantas", async () => {
    simularRutas((url) => (url.pathname === "/api/v1/organizaciones" ? json({ items: [...ORGS, { ...ORGS[1]!, id: 3, clave: "ORG03", activa: false }] }) : undefined));
    montar();
    expect(await screen.findByText("Empresa Grupo Industrial Norte")).toBeInTheDocument();
    const fila = screen.getByText("ORG01").closest("tr")!;
    expect(within(fila).getByText("GIN010101AB1")).toBeInTheDocument();
    expect(within(fila).getByText("Cargado")).toBeInTheDocument();
    expect(within(screen.getByText("ORG02").closest("tr")!).getByText("Sin logotipo")).toBeInTheDocument();
    expect(within(screen.getByText("ORG03").closest("tr")!).getByText("Inactiva")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plantas" })).toHaveAttribute("href", "/organizaciones/plantas");
    expect(screen.getByRole("link", { name: "Volver a colaboradores" })).toHaveAttribute("href", "/colaboradores");
  });

  it("crea una organización: clave y razón social obligatorias, RFC de 12 o 13 caracteres", async () => {
    const llamadas = simularRutas((url, metodo) => {
      if (url.pathname === "/api/v1/organizaciones" && metodo === "POST") return json({ ...ORGS[1]!, id: 9, clave: "ORG09", razon_social: "Nueva SA" }, 201);
      if (url.pathname === "/api/v1/organizaciones") return json({ items: ORGS });
      return undefined;
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "+ Nueva organización" }));
    const panel = screen.getByRole("complementary", { name: "Nueva organización" });
    await u.click(within(panel).getByRole("button", { name: "Guardar organización" }));
    expect(await within(panel).findAllByText("Este campo es obligatorio.")).toHaveLength(2); // clave y razón social

    await u.type(within(panel).getByLabelText("Clave"), "ORG09");
    await u.type(within(panel).getByLabelText("Razón social"), "Nueva SA");
    await u.type(within(panel).getByLabelText("RFC"), "ABC123");
    await u.click(within(panel).getByRole("button", { name: "Guardar organización" }));
    expect(await within(panel).findByText("El RFC debe tener 12 o 13 caracteres.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST")).toBe(false);

    await u.clear(within(panel).getByLabelText("RFC"));
    await u.type(within(panel).getByLabelText("RFC"), "NSA010101AB1");
    await u.click(within(panel).getByRole("button", { name: "Guardar organización" }));
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "POST")).toBe(true));
    expect(llamadas.find((l) => l.metodo === "POST")!.cuerpo).toEqual({
      clave: "ORG09",
      razon_social: "Nueva SA",
      rfc: "NSA010101AB1",
      registro_patronal: null,
      domicilio_fiscal: null,
      ciudad: null,
      nombre_firmante: null,
      cargo_firmante: null,
      correo_firmante: null,
    });
  });

  it("muestra el error por campo si la clave ya existe", async () => {
    simularRutas((url, metodo) => {
      if (url.pathname === "/api/v1/organizaciones" && metodo === "POST")
        return problema(409, "CLAVE_DUPLICADA", "Clave duplicada", { errores: [{ campo: "clave", codigo: "CLAVE_DUPLICADA", mensaje: "Ya existe una organización con esa clave." }] });
      if (url.pathname === "/api/v1/organizaciones") return json({ items: ORGS });
      return undefined;
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "+ Nueva organización" }));
    await u.type(screen.getByLabelText("Clave"), "ORG01");
    await u.type(screen.getByLabelText("Razón social"), "Otra");
    await u.click(screen.getByRole("button", { name: "Guardar organización" }));
    expect(await screen.findByText("Ya existe una organización con esa clave.")).toBeInTheDocument();
  });

  it("edición: la clave no cambia; se guardan los datos y se puede desactivar", async () => {
    const llamadas = simularRutas((url, metodo, init) => {
      if (url.pathname === "/api/v1/organizaciones/2" && metodo === "PATCH") return json({ ...ORGS[1]!, ...JSON.parse(String(init!.body)) });
      if (url.pathname === "/api/v1/organizaciones") return json({ items: ORGS });
      return undefined;
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar ORG02" }));
    const panel = screen.getByRole("complementary", { name: "Editar organización" });
    expect(within(panel).getByLabelText("Clave")).toBeDisabled();
    expect(within(panel).getByLabelText("Clave")).toHaveValue("ORG02");
    await u.type(within(panel).getByLabelText("Ciudad"), "Monterrey");
    await u.click(within(panel).getByRole("button", { name: "Guardar organización" }));
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "PATCH")).toBe(true));
    const patch = llamadas.find((l) => l.metodo === "PATCH")!;
    expect(patch.cuerpo.ciudad).toBe("Monterrey");
    expect(patch.cuerpo).not.toHaveProperty("clave");
    expect(await screen.findByText("Organización guardada.")).toBeInTheDocument();

    await u.click(within(panel).getByRole("button", { name: "Desactivar" }));
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "PATCH")).toHaveLength(2));
    expect(llamadas.filter((l) => l.metodo === "PATCH")[1]!.cuerpo).toEqual({ activa: false });
  });

  it("logotipo: solicita la URL firmada, sube directo a S3 y confirma", async () => {
    const llamadas = simularRutas((url, metodo) => {
      if (url.host === "s3.local") return new Response(null, { status: 200 });
      if (url.pathname === "/api/v1/organizaciones/2/logotipo" && metodo === "POST")
        return json({ url: "https://s3.local/logotipos/1/2.png?firma=x", s3_key: "logotipos/1/2.png", expira: "2026-11-13T16:00:00Z" });
      if (url.pathname === "/api/v1/organizaciones/2/logotipo/confirmar") return json({ ...ORGS[1]!, tiene_logotipo: true });
      if (url.pathname === "/api/v1/organizaciones") return json({ items: ORGS });
      return undefined;
    });
    const u = userEvent.setup();
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar ORG02" }));
    const png = new File([new Uint8Array(500)], "logo.png", { type: "image/png" });
    await u.upload(screen.getByLabelText("Archivo de logotipo"), png);
    await u.click(screen.getByRole("button", { name: "Subir logotipo" }));

    expect(await screen.findByText("Logotipo actualizado.")).toBeInTheDocument();
    const escrituras = llamadas.filter((l) => l.metodo !== "GET");
    expect(escrituras.map((l) => `${l.metodo} ${l.url.split("?")[0]}`)).toEqual([
      "POST /api/v1/organizaciones/2/logotipo",
      "PUT /logotipos/1/2.png",
      "POST /api/v1/organizaciones/2/logotipo/confirmar",
    ]);
    expect(escrituras[0]!.cuerpo).toEqual({ content_type: "image/png", tamano: 500 });
    expect((escrituras[1]!.init!.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(escrituras[2]!.cuerpo).toEqual({ s3_key: "logotipos/1/2.png" });
  });

  it("logotipo: rechaza formatos distintos de PNG o JPG y archivos de más de 1 MB", async () => {
    const llamadas = simularRutas((url) => (url.pathname === "/api/v1/organizaciones" ? json({ items: ORGS }) : undefined));
    const u = userEvent.setup({ applyAccept: false });
    montar();
    await u.click(await screen.findByRole("button", { name: "Editar ORG02" }));
    const campo = screen.getByLabelText("Archivo de logotipo");
    await u.upload(campo, new File(["x"], "logo.gif", { type: "image/gif" }));
    expect(await screen.findByText("El logotipo debe ser PNG o JPG.")).toBeInTheDocument();

    const grande = new File([new Uint8Array(10)], "logo.jpg", { type: "image/jpeg" });
    Object.defineProperty(grande, "size", { value: 2 * 1024 * 1024 });
    await u.upload(campo, grande);
    expect(await screen.findByText("El logotipo no puede pesar más de 1 MB.")).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Subir logotipo" }));
    expect(await screen.findByText("Elige un archivo.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST")).toBe(false);
  });
});

describe("plantas", () => {
  it("lista, agrega, renombra y desactiva o reactiva plantas", async () => {
    const llamadas = simularRutas((url, metodo, init) => {
      if (url.pathname === "/api/v1/plantas" && metodo === "POST") return json({ id: 3, nombre: JSON.parse(String(init!.body)).nombre, activa: true }, 201);
      if (url.pathname.startsWith("/api/v1/plantas/") && metodo === "PATCH") return json({ ...PLANTAS[0]!, ...JSON.parse(String(init!.body)) });
      if (url.pathname === "/api/v1/plantas") return json({ items: [...PLANTAS, { id: 4, nombre: "Saltillo", activa: false }] });
      return undefined;
    });
    const u = userEvent.setup();
    montar("/organizaciones/plantas");
    expect(await screen.findByText("Apodaca")).toBeInTheDocument();
    expect(within(screen.getByText("Saltillo").closest("tr")!).getByText("Inactiva")).toBeInTheDocument();

    await u.type(screen.getByLabelText("Nombre de la planta"), "Guadalajara");
    await u.click(screen.getByRole("button", { name: "Agregar planta" }));
    await waitFor(() => expect(llamadas.some((l) => l.metodo === "POST")).toBe(true));
    expect(llamadas.find((l) => l.metodo === "POST")!.cuerpo).toEqual({ nombre: "Guadalajara" });

    await u.click(screen.getByRole("button", { name: "Renombrar Apodaca" }));
    const entrada = screen.getByLabelText("Nombre de la planta Apodaca");
    await u.clear(entrada);
    await u.type(entrada, "Apodaca Norte");
    await u.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(llamadas.some((l) => l.url === "/api/v1/plantas/1" && l.metodo === "PATCH")).toBe(true));
    expect(llamadas.find((l) => l.url === "/api/v1/plantas/1")!.cuerpo).toEqual({ nombre: "Apodaca Norte" });

    await u.click(screen.getByRole("button", { name: "Desactivar Monterrey" }));
    await waitFor(() => expect(llamadas.some((l) => l.url === "/api/v1/plantas/2")).toBe(true));
    expect(llamadas.find((l) => l.url === "/api/v1/plantas/2")!.cuerpo).toEqual({ activa: false });

    await u.click(screen.getByRole("button", { name: "Activar Saltillo" }));
    await waitFor(() => expect(llamadas.some((l) => l.url === "/api/v1/plantas/4")).toBe(true));
    expect(llamadas.find((l) => l.url === "/api/v1/plantas/4")!.cuerpo).toEqual({ activa: true });
  });

  it("valida el nombre vacío y muestra el error de nombre duplicado", async () => {
    simularRutas((url, metodo) => {
      if (url.pathname === "/api/v1/plantas" && metodo === "POST")
        return problema(409, "PLANTA_DUPLICADA", "Duplicada", { errores: [{ campo: "nombre", codigo: "PLANTA_DUPLICADA", mensaje: "Ya existe una planta con ese nombre." }] });
      if (url.pathname === "/api/v1/plantas") return json({ items: PLANTAS });
      return undefined;
    });
    const u = userEvent.setup();
    montar("/organizaciones/plantas");
    await screen.findByText("Monterrey");
    await u.click(screen.getByRole("button", { name: "Agregar planta" }));
    expect(await screen.findByText("Este campo es obligatorio.")).toBeInTheDocument();
    await u.type(screen.getByLabelText("Nombre de la planta"), "monterrey");
    await u.click(screen.getByRole("button", { name: "Agregar planta" }));
    expect(await screen.findByText("Ya existe una planta con ese nombre.")).toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el listado de organizaciones no tiene violaciones críticas ni serias de axe", async () => {
    simularRutas((url) => (url.pathname === "/api/v1/organizaciones" ? json({ items: ORGS }) : undefined));
    const { container } = montar();
    await screen.findByText("Empresa Grupo Industrial Norte");
    await esperarAccesible(container);
  });
});
