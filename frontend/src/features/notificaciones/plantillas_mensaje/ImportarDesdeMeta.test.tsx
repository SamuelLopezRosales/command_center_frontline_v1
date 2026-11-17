import { configure, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "@/test/ayudantes";
import { esperarAccesible } from "@/test/axe";
import { RutasNotificaciones } from "../RutasNotificaciones";
import { json, plantillaMensaje, problema, simulador, type Llamada } from "../test/datos";
import type { PlantillaDeMeta, ResultadoImportacion } from "./api";

vi.setConfig({ testTimeout: 20000 });
configure({ asyncUtilTimeout: 8000 });

afterEach(() => vi.unstubAllGlobals());

function deMeta(sobre: Partial<PlantillaDeMeta> = {}): PlantillaDeMeta {
  return {
    nombre: "bienvenida_colaborador",
    idioma: "es_MX",
    categoria: "UTILITY",
    estado_meta: "APPROVED",
    id_plantilla_meta: "800000000000001",
    texto: "Hola {{1}}, te damos la bienvenida a {{2}}.",
    num_variables: 2,
    compatible: true,
    codigo_incompatible: null,
    motivo_incompatible: null,
    advertencias: [],
    ya_importada: false,
    nombre_en_uso: false,
    ...sobre,
  };
}

const LISTA_META: PlantillaDeMeta[] = [
  deMeta({ advertencias: ["Tiene pie de página fijo: Meta lo agrega al mensaje al enviar, pero Command Center no lo muestra en la vista previa."] }),
  deMeta({
    nombre: "bienvenida_corta",
    id_plantilla_meta: "800000000000007",
    texto: "Bienvenido {{1}}.",
    num_variables: 1,
  }),
  deMeta({
    nombre: "bienvenida_con_boton",
    id_plantilla_meta: "800000000000002",
    compatible: false,
    codigo_incompatible: "TIENE_BOTONES",
    motivo_incompatible: "Tiene botones: solo se admiten plantillas con cuerpo de texto.",
  }),
  deMeta({
    nombre: "bienvenida_pausada",
    id_plantilla_meta: "800000000000006",
    estado_meta: "PAUSED",
    compatible: false,
    codigo_incompatible: "ESTADO_NO_APROBADO",
    motivo_incompatible: "Está pausada en Meta: solo se importan las plantillas aprobadas.",
  }),
  deMeta({ nombre: "aviso_ya_importado", id_plantilla_meta: "800000000000008", ya_importada: true }),
  deMeta({ nombre: "aviso_nombre_repetido", id_plantilla_meta: "800000000000009", nombre_en_uso: true }),
];

const URL_LISTA = "GET /api/v1/plantillas-mensaje/meta";
const URL_IMPORTAR = "POST /api/v1/plantillas-mensaje/importar";

const montar = () =>
  renderizar(
    <Routes>
      <Route path="notificaciones/*" element={<RutasNotificaciones />} />
      <Route path="integraciones/meta" element={<p>Pantalla de conexión con Meta</p>} />
    </Routes>,
    { ruta: "/notificaciones/plantillas" },
  );

async function abrir() {
  await userEvent.click(await screen.findByRole("button", { name: "Importar desde Meta" }));
  return screen.findByRole("dialog", { name: "Importar plantillas desde Meta" });
}

const base = (extra: Record<string, unknown> = {}) => ({
  "GET /api/v1/plantillas-mensaje": { items: [plantillaMensaje()], siguiente: null },
  ...extra,
});

describe("importar plantillas desde Meta", () => {
  it("lista lo de Meta con insignias y casillas solo en lo importable", async () => {
    simulador(base({ [URL_LISTA]: { items: LISTA_META, truncado: false } }));
    montar();
    const dialogo = await abrir();
    const tabla = await within(dialogo).findByRole("table", { name: "Plantillas de Meta" });
    const fila = (nombre: string) => within(within(tabla).getAllByRole("row").find((r) => within(r).queryByText(nombre))!);

    const compatible = fila("bienvenida_colaborador");
    expect(compatible.getByText("Compatible")).toBeInTheDocument();
    expect(compatible.getByText("Hola {{1}}, te damos la bienvenida a {{2}}.")).toBeInTheDocument();
    expect(compatible.getByText("2 variables")).toBeInTheDocument();
    expect(compatible.getByText("Aprobada")).toBeInTheDocument();
    expect(compatible.getByText("Utilidad")).toBeInTheDocument();
    expect(compatible.getByText("es_MX")).toBeInTheDocument();
    expect(compatible.getByText(/Tiene pie de página fijo/)).toBeInTheDocument();
    expect(compatible.getByRole("checkbox", { name: "Seleccionar bienvenida_colaborador (es_MX)" })).toBeInTheDocument();

    const boton = fila("bienvenida_con_boton");
    expect(boton.getByText(/No compatible: Tiene botones/)).toBeInTheDocument();
    expect(boton.queryByRole("checkbox")).not.toBeInTheDocument();

    const pausada = fila("bienvenida_pausada");
    expect(pausada.getByText("Pausada")).toBeInTheDocument();
    expect(pausada.getByText(/No compatible: Está pausada en Meta/)).toBeInTheDocument();
    expect(pausada.queryByRole("checkbox")).not.toBeInTheDocument();

    const ya = fila("aviso_ya_importado");
    expect(ya.getByText("Ya importada")).toBeInTheDocument();
    expect(ya.queryByRole("checkbox")).not.toBeInTheDocument();

    const enUso = fila("aviso_nombre_repetido");
    expect(enUso.getByText(/Nombre en uso/)).toBeInTheDocument();
    expect(enUso.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("selecciona una o todas las compatibles y habilita «Importar seleccionadas»", async () => {
    simulador(base({ [URL_LISTA]: { items: LISTA_META, truncado: false } }));
    montar();
    const dialogo = await abrir();
    const importar = await within(dialogo).findByRole("button", { name: "Importar seleccionadas (0)" });
    expect(importar).toBeDisabled();

    await userEvent.click(within(dialogo).getByRole("checkbox", { name: "Seleccionar bienvenida_corta (es_MX)" }));
    expect(within(dialogo).getByText("1 seleccionada")).toBeInTheDocument();
    expect(within(dialogo).getByRole("button", { name: "Importar seleccionadas (1)" })).toBeEnabled();

    const todas = within(dialogo).getByRole("checkbox", { name: "Seleccionar todas las compatibles" });
    await userEvent.click(todas);
    expect(within(dialogo).getByText("2 seleccionadas")).toBeInTheDocument();
    expect(todas).toBeChecked();
    // Solo se marcan las compatibles y no importadas: 2 de 6.
    const marcadas = within(dialogo).getAllByRole("checkbox").filter((c) => (c as HTMLInputElement).checked);
    expect(marcadas).toHaveLength(3); // las dos filas y «todas»

    await userEvent.click(todas);
    expect(within(dialogo).getByRole("button", { name: "Importar seleccionadas (0)" })).toBeDisabled();
  });

  it("importa lo elegido mandando solo nombre e idioma, muestra el resumen y refresca la lista local", async () => {
    let importado = false;
    const resultado: ResultadoImportacion[] = [
      { nombre: "bienvenida_colaborador", idioma: "es_MX", resultado: "IMPORTADA", motivo: null, codigo: null, plantilla_id: 11 },
      { nombre: "bienvenida_corta", idioma: "es_MX", resultado: "YA_EXISTIA", motivo: null, codigo: null, plantilla_id: 12 },
      {
        nombre: "bienvenida_pausada",
        idioma: "es_MX",
        resultado: "OMITIDA",
        motivo: "Está pausada en Meta: solo se importan las plantillas aprobadas.",
        codigo: "ESTADO_NO_APROBADO",
        plantilla_id: null,
      },
    ];
    const llamadas = simulador({
      "GET /api/v1/plantillas-mensaje": () =>
        json({ items: importado ? [plantillaMensaje(), plantillaMensaje({ id: 11, nombre: "bienvenida_colaborador" })] : [plantillaMensaje()], siguiente: null }),
      [URL_LISTA]: () =>
        json({ items: LISTA_META.map((p) => (importado && p.nombre === "bienvenida_colaborador" ? { ...p, ya_importada: true } : p)), truncado: false }),
      [URL_IMPORTAR]: () => {
        importado = true;
        return json({ items: resultado });
      },
    });
    montar();
    const dialogo = await abrir();
    await userEvent.click(await within(dialogo).findByRole("checkbox", { name: "Seleccionar todas las compatibles" }));
    await userEvent.click(within(dialogo).getByRole("button", { name: "Importar seleccionadas (2)" }));

    const resumen = await within(dialogo).findByRole("table", { name: "Resultado de la importación" });
    expect(within(dialogo).getByText("1 importada, 1 ya existía, 1 omitida.")).toBeInTheDocument();
    expect(within(resumen).getByText("Importada")).toBeInTheDocument();
    expect(within(resumen).getByText("Ya existía")).toBeInTheDocument();
    expect(within(resumen).getByText(/Omitida: Está pausada en Meta/)).toBeInTheDocument();

    const envio = llamadas.find((l) => l.metodo === "POST" && l.ruta.endsWith("/importar"))!;
    expect(envio.cuerpo).toEqual({
      plantillas: [
        { nombre: "bienvenida_colaborador", idioma: "es_MX" },
        { nombre: "bienvenida_corta", idioma: "es_MX" },
      ],
    });

    // La lista local se refrescó y, al volver, la de Meta marca la importada.
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "GET" && l.ruta === "/api/v1/plantillas-mensaje").length).toBeGreaterThanOrEqual(2));
    await userEvent.click(within(dialogo).getByRole("button", { name: "Volver a la lista" }));
    const fila = within((await within(dialogo).findAllByRole("row")).find((r) => within(r).queryByText("bienvenida_colaborador"))!);
    await waitFor(() => expect(fila.getByText("Ya importada")).toBeInTheDocument());

    await userEvent.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(await screen.findByText("1 plantilla importada desde Meta.")).toBeInTheDocument();
    const catalogo = await screen.findByRole("table", { name: "Plantillas de mensaje" });
    expect(await within(catalogo).findByText("bienvenida_colaborador")).toBeInTheDocument();
  });

  it("el texto de Meta se muestra como texto, nunca como HTML", async () => {
    simulador(
      base({
        [URL_LISTA]: {
          items: [deMeta({ texto: '<img src=x onerror="alert(1)"> Hola {{1}}', num_variables: 1 })],
          truncado: false,
        },
      }),
    );
    const { container } = montar();
    const dialogo = await abrir();
    expect(await within(dialogo).findByText(/<img src=x onerror="alert\(1\)"> Hola \{\{1\}\}/)).toBeInTheDocument();
    expect(container.ownerDocument.querySelector("img")).toBeNull();
  });

  it("estado vacío: Meta no tiene plantillas aprobadas", async () => {
    simulador(base({ [URL_LISTA]: { items: [], truncado: false } }));
    montar();
    const dialogo = await abrir();
    expect(await within(dialogo).findByText("Meta no tiene plantillas aprobadas.")).toBeInTheDocument();
    expect(within(dialogo).queryByRole("table")).not.toBeInTheDocument();
  });

  it("avisa cuando Meta tiene más de las que se muestran", async () => {
    simulador(base({ [URL_LISTA]: { items: LISTA_META, truncado: true } }));
    montar();
    const dialogo = await abrir();
    expect(await within(dialogo).findByText(/Meta tiene más plantillas de las que se muestran/)).toBeInTheDocument();
  });

  it("muestra el cargando mientras consulta", async () => {
    let soltar: (r: Response) => void = () => {};
    simulador(base({ [URL_LISTA]: () => new Promise<Response>((res) => (soltar = res)) }));
    montar();
    const dialogo = await abrir();
    expect(within(dialogo).getByRole("status")).toHaveTextContent("Consultando las plantillas de Meta…");
    soltar(json({ items: [], truncado: false }));
    expect(await within(dialogo).findByText("Meta no tiene plantillas aprobadas.")).toBeInTheDocument();
  });

  it("error de Meta: muestra el mensaje en español del servidor y permite reintentar", async () => {
    let intentos = 0;
    simulador(
      base({
        [URL_LISTA]: () => {
          intentos += 1;
          return intentos === 1
            ? problema(502, "ERROR_PROVEEDOR_META", "Meta rechazó el token de acceso: no es válido o ya venció. Genere uno nuevo y guárdelo.")
            : json({ items: LISTA_META, truncado: false });
        },
      }),
    );
    montar();
    const dialogo = await abrir();
    expect(await within(dialogo).findByRole("alert")).toHaveTextContent("Meta rechazó el token de acceso");
    await userEvent.click(within(dialogo).getByRole("button", { name: "Reintentar" }));
    expect(await within(dialogo).findByRole("table", { name: "Plantillas de Meta" })).toBeInTheDocument();
  });

  it("META_NO_CONFIGURADA guía a «Conexión con Meta»", async () => {
    simulador(base({ [URL_LISTA]: () => problema(422, "META_NO_CONFIGURADA", "Faltan credenciales de Meta.") }));
    montar();
    const dialogo = await abrir();
    expect(await within(dialogo).findByRole("alert")).toHaveTextContent("La conexión con Meta no está configurada");
    const enlace = within(dialogo).getByRole("link", { name: "Ir a Conexión con Meta" });
    expect(enlace).toHaveAttribute("href", "/integraciones/meta");
    expect(within(dialogo).queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
  });

  it("un fallo al importar conserva la lista y la selección", async () => {
    simulador(
      base({
        [URL_LISTA]: { items: LISTA_META, truncado: false },
        [URL_IMPORTAR]: () => problema(502, "ERROR_PROVEEDOR_META", "Meta no respondió a tiempo. Intente de nuevo en unos minutos."),
      }),
    );
    montar();
    const dialogo = await abrir();
    await userEvent.click(await within(dialogo).findByRole("checkbox", { name: "Seleccionar bienvenida_corta (es_MX)" }));
    await userEvent.click(within(dialogo).getByRole("button", { name: "Importar seleccionadas (1)" }));
    expect(await within(dialogo).findByRole("alert")).toHaveTextContent("Meta no respondió a tiempo");
    expect(within(dialogo).getByRole("checkbox", { name: "Seleccionar bienvenida_corta (es_MX)" })).toBeChecked();
    expect(within(dialogo).getByRole("button", { name: "Importar seleccionadas (1)" })).toBeEnabled();
  });

  it("Escape cierra el diálogo", async () => {
    simulador(base({ [URL_LISTA]: { items: LISTA_META, truncado: false } }));
    montar();
    const dialogo = await abrir();
    await within(dialogo).findByRole("table", { name: "Plantillas de Meta" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("accesibilidad de importar desde Meta (CC-NFR-012)", () => {
  it("la lista y el resumen no tienen violaciones críticas ni serias de axe", async () => {
    simulador(
      base({
        [URL_LISTA]: { items: LISTA_META, truncado: true },
        [URL_IMPORTAR]: (_l: Llamada) =>
          json({ items: [{ nombre: "bienvenida_corta", idioma: "es_MX", resultado: "IMPORTADA", motivo: null, codigo: null, plantilla_id: 1 }] }),
      }),
    );
    const { baseElement } = montar();
    const dialogo = await abrir();
    await userEvent.click(await within(dialogo).findByRole("checkbox", { name: "Seleccionar todas las compatibles" }));
    await esperarAccesible(baseElement);
    await userEvent.click(within(dialogo).getByRole("button", { name: "Importar seleccionadas (2)" }));
    await within(dialogo).findByRole("table", { name: "Resultado de la importación" });
    await esperarAccesible(baseElement);
  });

  it("los estados de error y no configurada tampoco tienen violaciones", async () => {
    simulador(base({ [URL_LISTA]: () => problema(422, "META_NO_CONFIGURADA", "Faltan credenciales de Meta.") }));
    const { baseElement } = montar();
    const dialogo = await abrir();
    await within(dialogo).findByRole("alert");
    await esperarAccesible(baseElement);
  });
});
