import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { listadoCampos, ORGS, PLANTAS } from "@/test/fixturas220";
import { renderizar } from "@/test/ayudantes";
import { RutasNotificaciones } from "../RutasNotificaciones";
import { json, notificacion, plantillaMensaje, problema, REVISION_CV1_09, simulador, type Llamada } from "../test/datos";
import { esperarAccesible } from "@/test/axe";

// Las pruebas con muchos pasos de usuario tardan más que el límite por defecto.
vi.setConfig({ testTimeout: 20000 });
configure({ asyncUtilTimeout: 8000 });

afterEach(() => vi.unstubAllGlobals());

type Rutas = Parameters<typeof simulador>[0];

const BORRADOR = notificacion({ id: 9, estado: "BORRADOR", titulo: "Entrega de uniformes", fecha_envio: null, confirmada_en: null });

/** Catálogos del formulario y, por defecto, un envío que sale bien. */
function api(extra: Rutas = {}) {
  return simulador({
    "GET /api/v1/campos": listadoCampos(),
    "GET /api/v1/organizaciones": { items: ORGS },
    "GET /api/v1/plantas": { items: PLANTAS },
    "GET /api/v1/plantillas-mensaje": { items: [plantillaMensaje()], siguiente: null },
    "GET /api/v1/audiencias": {
      items: [{ id: 3, nombre: "Planta Apodaca · Operativo", activa: true, criterios: {}, creada_por_usuario_id: 1, fecha_creacion: "2026-11-01T10:00:00Z" }],
      siguiente: null,
    },
    "POST /api/v1/notificaciones": () => json(BORRADOR, 201),
    "PATCH /api/v1/notificaciones/9": () => json(BORRADOR),
    "POST /api/v1/notificaciones/9/revisar": REVISION_CV1_09,
    "POST /api/v1/notificaciones/9/confirmar": () => json({ ...BORRADOR, estado: "ENVIANDO" }, 202),
    "GET /api/v1/notificaciones/9": { ...BORRADOR, estado: "ENVIANDO" },
    "GET /api/v1/notificaciones/9/destinatarios": { items: [], siguiente: null },
    ...extra,
  });
}

const montar = (ruta = "/notificaciones/nueva") =>
  renderizar(
    <Routes>
      <Route path="notificaciones/*" element={<RutasNotificaciones />} />
    </Routes>,
    { ruta },
  );

/** Espera a que los catálogos estén cargados (opciones de campo y de plantilla). */
async function esperarCatalogos() {
  await waitFor(() => {
    expect(within(screen.getByLabelText("Campo 1")).getByRole("option", { name: "Planta" })).toBeInTheDocument();
    expect(within(screen.getByLabelText("Plantilla")).getByRole("option", { name: /recordatorio_uniformes_v1/ })).toBeInTheDocument();
  });
}

/** Modo GRUPO con título, plantilla aprobada y las dos variables: lo mínimo para guardar. */
async function completar(user: ReturnType<typeof userEvent.setup>) {
  await esperarCatalogos();
  await user.type(screen.getByLabelText("Título del envío"), "Entrega de uniformes");
  await user.click(screen.getByRole("radio", { name: "Grupo guardado" }));
  await user.selectOptions(await screen.findByLabelText("Grupo guardado", { selector: "select" }), "3");
  await user.selectOptions(screen.getByLabelText("Plantilla"), "5");
  await user.selectOptions(screen.getByLabelText("Campo de {{1}}"), "nombre_completo");
  await user.selectOptions(screen.getByLabelText("Origen de {{2}}"), "FIJO");
  await user.type(screen.getByLabelText("Valor fijo de {{2}}"), "13 nov 2026");
}

const ultima = (llamadas: Llamada[], metodo: string, fin: string) => llamadas.filter((l) => l.metodo === metodo && l.ruta.endsWith(fin)).at(-1);
const guardar = () => screen.getAllByRole("button", { name: "Guardar borrador" })[0]!;

describe("constructor de criterios (cv1_09)", () => {
  it("arma criterios con Y, O, un grupo y antigüedad, y los manda con el formato del contrato", async () => {
    const llamadas = api();
    const user = userEvent.setup();
    montar();
    await esperarCatalogos();

    await user.type(screen.getByLabelText("Título del envío"), "Uniformes");
    // Criterio 1: planta es Apodaca.
    await user.selectOptions(screen.getByLabelText("Campo 1"), "planta_id");
    await user.selectOptions(screen.getByLabelText("Valor 1"), "1");
    // Criterio 2: tipo de empleado es Operativo.
    await user.click(screen.getByRole("button", { name: "+ Agregar criterio" }));
    await user.selectOptions(screen.getByLabelText("Campo 2"), "tipo_empleado");
    await user.selectOptions(screen.getByLabelText("Valor 2"), "OPERATIVO");
    // Criterio 3: antigüedad ≥ 5 años.
    await user.click(screen.getByRole("button", { name: "+ Agregar criterio" }));
    await user.selectOptions(screen.getByLabelText("Campo 3"), "antiguedad_anios");
    await user.selectOptions(screen.getByLabelText("Operador 3"), ">=");
    await user.type(screen.getByLabelText("Valor 3"), "5");
    expect(screen.getByText("años")).toBeInTheDocument();

    // Por defecto se combinan con Y; el combinador se puede cambiar a O.
    const pildoras = screen.getAllByRole("button", { name: "Combinador: Y (todos). Cambiar" });
    expect(pildoras).toHaveLength(2);
    await user.click(pildoras[0]!);
    expect(screen.getAllByRole("button", { name: "Combinador: O (cualquiera). Cambiar" })).toHaveLength(2);

    // Un grupo anidado (Y) con un campo personalizado de lista.
    await user.click(screen.getByRole("button", { name: "+ Agregar grupo (Y/O)" }));
    await user.selectOptions(screen.getByLabelText("Campo 4"), "CAMP-0001");
    await user.selectOptions(screen.getByLabelText("Valor 4"), "PRODUCCION");

    // Los campos sensibles y los inactivos no se pueden elegir.
    const opciones = within(screen.getByLabelText("Campo 1")).getAllByRole("option").map((o) => o.textContent);
    expect(opciones).toContain("Antigüedad (años)");
    expect(opciones).toContain("Área");
    expect(opciones).not.toContain("Sueldo (MXN)");
    expect(opciones).not.toContain("NSS");
    expect(opciones).not.toContain("Ruta de transporte");

    await user.selectOptions(screen.getByLabelText("Plantilla"), "5");
    await user.selectOptions(screen.getByLabelText("Campo de {{1}}"), "nombre_completo");
    await user.selectOptions(screen.getByLabelText("Campo de {{2}}"), "planta");
    await user.click(guardar());

    await waitFor(() => expect(ultima(llamadas, "POST", "/api/v1/notificaciones")).toBeDefined());
    const cuerpo = ultima(llamadas, "POST", "/api/v1/notificaciones")!.cuerpo as Record<string, unknown>;
    expect(cuerpo).toEqual({
      titulo: "Uniformes",
      modo: "CRITERIOS",
      criterios: {
        op: "O",
        items: [
          { campo: "planta_id", operador: "es", valor: 1 },
          { campo: "tipo_empleado", operador: "es", valor: "OPERATIVO" },
          { campo: "antiguedad_anios", operador: ">=", valor: 5 },
          { op: "Y", items: [{ campo: "CAMP-0001", operador: "es", valor: "PRODUCCION" }] },
        ],
      },
      plantilla_mensaje_id: 5,
      variables: { "1": { origen: "COLABORADOR", campo: "nombre_completo" }, "2": { origen: "COLABORADOR", campo: "planta" } },
      respaldo_correo: false,
      zona_horaria: "America/Mexico_City",
    });
    // No existe texto libre en el contrato.
    expect(cuerpo).not.toHaveProperty("mensaje");
    expect(cuerpo).not.toHaveProperty("texto");
    expect(await screen.findByText("Borrador guardado.")).toBeInTheDocument();
  });

  it("valida en pantalla antes de guardar: criterio incompleto, antigüedad fuera de rango y rango invertido", async () => {
    const llamadas = api();
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("radio", { name: "Por criterios" }));
    await user.click(guardar());
    expect(await screen.findByText("Indica un valor.")).toBeInTheDocument();
    expect(ultima(llamadas, "POST", "/api/v1/notificaciones")).toBeUndefined();

    await user.selectOptions(screen.getByLabelText("Campo 1"), "antiguedad_anios");
    await user.type(screen.getByLabelText("Valor 1"), "95");
    await user.click(guardar());
    expect(await screen.findByText("La antigüedad va de 0 a 80 años.")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Operador 1"), "entre");
    await user.clear(screen.getByLabelText("Valor 1"));
    await user.type(screen.getByLabelText("Valor 1"), "10");
    await user.type(screen.getByLabelText("Valor final 1"), "5");
    await user.click(guardar());
    expect(await screen.findByText("El primer valor no puede ser mayor que el segundo.")).toBeInTheDocument();
    expect(ultima(llamadas, "POST", "/api/v1/notificaciones")).toBeUndefined();
  });

  it("muestra el error del servidor junto al criterio que lo causó", async () => {
    api({
      "POST /api/v1/notificaciones": () =>
        problema(422, "VALIDACION", "Revisa los criterios", [
          { campo: "criterios.items.0.valor", codigo: "OPCION_DESCONOCIDA", mensaje: "La opción no existe o está inactiva." },
        ]),
    });
    const user = userEvent.setup();
    montar();
    await esperarCatalogos();
    await user.type(screen.getByLabelText("Título del envío"), "Uniformes");
    await user.selectOptions(screen.getByLabelText("Campo 1"), "CAMP-0001");
    await user.selectOptions(screen.getByLabelText("Valor 1"), "ALMACEN");
    await user.selectOptions(screen.getByLabelText("Plantilla"), "5");
    await user.selectOptions(screen.getByLabelText("Campo de {{1}}"), "nombre_completo");
    await user.selectOptions(screen.getByLabelText("Campo de {{2}}"), "planta");
    await user.click(guardar());
    expect(await screen.findByText("La opción no existe o está inactiva.")).toBeInTheDocument();
  });
});

describe("modos de audiencia", () => {
  it("modo INDIVIDUAL: busca un colaborador y manda su id", async () => {
    const llamadas = api({
      "GET /api/v1/colaboradores": {
        items: [{ id: 21, numero_empleado: "EMP-0021", nombre_completo: "Ricardo Salinas Ibarra", planta: { id: 1, nombre: "Apodaca" }, organizacion: { id: 1, nombre: "ORG01" } }],
        limite: 8,
        pagina: 1,
        total: 1,
      },
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("radio", { name: "Individual" }));
    await user.type(screen.getByLabelText("Buscar colaborador por nombre o número de empleado"), "Ricar");
    await user.click(await screen.findByRole("button", { name: "Elegir Ricardo Salinas Ibarra" }));
    expect(screen.getByText("Colaborador elegido: Ricardo Salinas Ibarra")).toBeInTheDocument();
    await user.click(guardar());
    await waitFor(() => expect(ultima(llamadas, "POST", "/api/v1/notificaciones")).toBeDefined());
    const c = ultima(llamadas, "POST", "/api/v1/notificaciones")!.cuerpo as Record<string, unknown>;
    expect(c).toMatchObject({ modo: "INDIVIDUAL", colaborador_id: 21 });
    expect(c).not.toHaveProperty("criterios");
    expect(c).not.toHaveProperty("audiencia_id");
  });

  it("modo GRUPO: manda el id del grupo guardado y nada más de la audiencia", async () => {
    const llamadas = api();
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(guardar());
    await waitFor(() => expect(ultima(llamadas, "POST", "/api/v1/notificaciones")).toBeDefined());
    const c = ultima(llamadas, "POST", "/api/v1/notificaciones")!.cuerpo as Record<string, unknown>;
    expect(c).toMatchObject({
      modo: "GRUPO",
      audiencia_id: 3,
      variables: { "1": { origen: "COLABORADOR", campo: "nombre_completo" }, "2": { origen: "FIJO", valor: "13 nov 2026" } },
    });
    expect(c).not.toHaveProperty("criterios");
  });

  it("la plantilla aprobada se previsualiza con las variables fijas y no hay campo de texto libre", async () => {
    api();
    const user = userEvent.setup();
    montar();
    await completar(user);
    expect(screen.getByText("Hola {{Nombre completo}}, te recordamos que mañana 13 nov 2026 se entregan uniformes.")).toBeInTheDocument();
    expect(screen.getByText("Plantilla aprobada por Meta")).toBeInTheDocument();
    expect(screen.queryByLabelText(/texto libre/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /mensaje/i })).not.toBeInTheDocument();
  });

  it("errores por campo: título, plantilla y variables vacíos no se guardan", async () => {
    const llamadas = api();
    const user = userEvent.setup();
    montar();
    await esperarCatalogos();
    await user.click(guardar());
    expect(await screen.findByText("Escribe un título para el envío.")).toBeInTheDocument();
    expect(screen.getByText("Elige una plantilla aprobada.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Plantilla"), "5");
    await user.click(guardar());
    expect(await screen.findAllByText("Elige un campo.")).toHaveLength(2);
    expect(ultima(llamadas, "POST", "/api/v1/notificaciones")).toBeUndefined();
  });

  it("errores por campo del servidor se muestran en su campo", async () => {
    api({
      "POST /api/v1/notificaciones": () =>
        problema(422, "VALIDACION", "Revisa los datos", [
          { campo: "titulo", codigo: "TITULO_INVALIDO", mensaje: "Use de 1 a 150 caracteres." },
          { campo: "variables.2", codigo: "VARIABLE_FALTANTE", mensaje: "Asigne esta variable." },
        ]),
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(guardar());
    expect(await screen.findByText("Use de 1 a 150 caracteres.")).toBeInTheDocument();
    expect(screen.getByText("Asigne esta variable.")).toBeInTheDocument();
  });
});

describe("plantillas con variables con nombre", () => {
  const NOMBRADA = plantillaMensaje({
    id: 6,
    nombre: "vida_aviso_checkout",
    texto_con_variables: "Hola {{guest_name}}, tu salida es a las {{checkout_time}}.",
    ejemplos: ["Juan", "12:00"],
    cantidad_variables: 2,
    formato_variables: "NOMBRADO",
    variables: ["guest_name", "checkout_time"],
  });
  const rutas = (extra: Rutas = {}): Rutas => ({ "GET /api/v1/plantillas-mensaje": { items: [plantillaMensaje(), NOMBRADA], siguiente: null }, ...extra });

  async function elegirNombrada(user: ReturnType<typeof userEvent.setup>) {
    await waitFor(() => expect(within(screen.getByLabelText("Plantilla")).getByRole("option", { name: /vida_aviso_checkout/ })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Plantilla"), "6");
  }

  it("muestra una fila por nombre de variable (en monoespaciado) en lugar de numeradas", async () => {
    api(rutas());
    const user = userEvent.setup();
    montar();
    await elegirNombrada(user);
    expect(screen.getByText("Variables (con nombre)")).toBeInTheDocument();
    for (const n of ["guest_name", "checkout_time"]) {
      const etiqueta = screen.getByText(n);
      expect(etiqueta.tagName).toBe("CODE");
      expect(screen.getByLabelText(`Origen de {{${n}}}`)).toBeInTheDocument();
    }
    expect(screen.queryByLabelText("Origen de {{1}}")).not.toBeInTheDocument();
  });

  it("la vista previa sustituye por nombre y la notificación se guarda con variables por nombre", async () => {
    const llamadas = api(rutas());
    const user = userEvent.setup();
    montar();
    await esperarCatalogos();
    await user.type(screen.getByLabelText("Título del envío"), "Aviso de salida");
    await user.click(screen.getByRole("radio", { name: "Grupo guardado" }));
    await user.selectOptions(await screen.findByLabelText("Grupo guardado", { selector: "select" }), "3");
    await elegirNombrada(user);
    await user.selectOptions(screen.getByLabelText("Campo de {{guest_name}}"), "nombre_completo");
    await user.selectOptions(screen.getByLabelText("Origen de {{checkout_time}}"), "FIJO");
    await user.type(screen.getByLabelText("Valor fijo de {{checkout_time}}"), "12:00");
    expect(screen.getByText("Hola {{Nombre completo}}, tu salida es a las 12:00.")).toBeInTheDocument();
    await user.click(guardar());
    await waitFor(() => expect(ultima(llamadas, "POST", "/api/v1/notificaciones")).toBeDefined());
    const cuerpo = ultima(llamadas, "POST", "/api/v1/notificaciones")!.cuerpo as { variables: Record<string, unknown>; plantilla_mensaje_id: number };
    expect(cuerpo.plantilla_mensaje_id).toBe(6);
    expect(cuerpo.variables).toEqual({
      guest_name: { origen: "COLABORADOR", campo: "nombre_completo" },
      checkout_time: { origen: "FIJO", valor: "12:00" },
    });
  });

  it("valida cada nombre y muestra el error del servidor en la fila del nombre", async () => {
    api(
      rutas({
        "POST /api/v1/notificaciones": () =>
          problema(422, "VALIDACION", "Revisa los datos", [{ campo: "variables.checkout_time", codigo: "VARIABLE_FALTANTE", mensaje: "Asigne esta variable." }]),
      }),
    );
    const user = userEvent.setup();
    montar();
    await esperarCatalogos();
    await user.type(screen.getByLabelText("Título del envío"), "Aviso de salida");
    await user.click(screen.getByRole("radio", { name: "Grupo guardado" }));
    await user.selectOptions(await screen.findByLabelText("Grupo guardado", { selector: "select" }), "3");
    await elegirNombrada(user);
    await user.click(guardar());
    expect(await screen.findAllByText("Elige un campo.")).toHaveLength(2); // una por nombre
    await user.selectOptions(screen.getByLabelText("Campo de {{guest_name}}"), "nombre_completo");
    await user.selectOptions(screen.getByLabelText("Campo de {{checkout_time}}"), "puesto");
    await user.click(guardar());
    expect(await screen.findByText("Asigne esta variable.")).toBeInTheDocument();
  });

  it("las numeradas siguen igual: una fila por posición, sin nombres", async () => {
    api(rutas());
    const user = userEvent.setup();
    montar();
    await esperarCatalogos();
    await user.selectOptions(screen.getByLabelText("Plantilla"), "5");
    expect(screen.getByText("Variables")).toBeInTheDocument();
    expect(screen.getByLabelText("Origen de {{1}}")).toBeInTheDocument();
    expect(screen.queryByText("Variables (con nombre)")).not.toBeInTheDocument();
  });

  it("no tiene violaciones de axe con variables con nombre", async () => {
    api(rutas());
    const user = userEvent.setup();
    const { baseElement } = montar();
    await elegirNombrada(user);
    await esperarAccesible(baseElement);
  });
});

describe("embudo y envío (cv1_09)", () => {
  it("muestra el embudo del ejemplo (61, 56, 54, 54) con los excluidos por motivo", async () => {
    const llamadas = api();
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));

    const embudo = await screen.findByRole("list", { name: "Embudo de la audiencia" });
    const filas = within(embudo).getAllByRole("listitem");
    expect(filas.map((f) => f.textContent)).toEqual(["Seleccionados61", "Con consentimiento56", "Estatus ACTIVO54", "Celular válido54"]);
    expect(screen.getByText("7 excluidos: 5 sin consentimiento y 2 con estatus BAJA.")).toBeInTheDocument();
    expect(screen.getByText("Se omiten automáticamente y quedan registrados.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar a 54 colaboradores" })).toBeEnabled();
    // Guarda el borrador y después revisa.
    expect(ultima(llamadas, "POST", "/api/v1/notificaciones/9/revisar")).toBeDefined();
  });

  it("desglosa tres motivos de exclusión", async () => {
    api({
      "POST /api/v1/notificaciones/9/revisar": {
        embudo: { seleccionados: 10, con_consentimiento: 9, activos: 8, celular_valido: 7 },
        excluidos_por_motivo: { SIN_CONSENTIMIENTO: 1, ESTATUS_BAJA: 1, SIN_CELULAR_VALIDO: 1 },
        total_seleccionados: 10,
        total_excluidos: 3,
        revisada_en: "2026-11-15T15:00:00Z",
      },
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    expect(await screen.findByText("3 excluidos: 1 sin consentimiento, 1 con estatus BAJA y 1 sin celular válido.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar a 7 colaboradores" })).toBeEnabled();
  });

  it("deshabilita «Enviar a N colaboradores» sin revisión y sin destinatarios válidos", async () => {
    api({
      "POST /api/v1/notificaciones/9/revisar": {
        embudo: { seleccionados: 2, con_consentimiento: 0, activos: 0, celular_valido: 0 },
        excluidos_por_motivo: { SIN_CONSENTIMIENTO: 2, ESTATUS_BAJA: 0, SIN_CELULAR_VALIDO: 0 },
        total_seleccionados: 2,
        total_excluidos: 2,
        revisada_en: "2026-11-15T15:00:00Z",
      },
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    // Antes de revisar no hay destinatarios.
    expect(screen.getByRole("button", { name: "Enviar a 0 colaboradores" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    expect(await screen.findByText("No hay destinatarios válidos. Ajusta la audiencia.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar a 0 colaboradores" })).toBeDisabled();
  });

  it("al cambiar la configuración la revisión queda obsoleta y hay que revisar de nuevo", async () => {
    api();
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    expect(await screen.findByRole("button", { name: "Enviar a 54 colaboradores" })).toBeEnabled();
    await user.type(screen.getByLabelText("Título del envío"), " 2");
    expect(screen.getByText("Cambiaste la configuración. Vuelve a revisar antes de enviar.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar a 54 colaboradores" })).toBeDisabled();
  });

  it("muestra la leyenda del horario y envía ahora con la confirmación del respaldo por correo", async () => {
    const llamadas = api();
    const user = userEvent.setup();
    montar();
    await completar(user);
    expect(screen.getByText("Horario de envío: 08:00 a 20:00 (America/Mexico_City)")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Si WhatsApp no entrega en 24 h/ }));
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    await user.click(await screen.findByRole("button", { name: "Enviar a 54 colaboradores" }));
    await waitFor(() => expect(ultima(llamadas, "POST", "/confirmar")).toBeDefined());
    expect(ultima(llamadas, "POST", "/confirmar")!.cuerpo).toEqual({ modo_envio: "AHORA", respaldo_correo: true, confirmar_fuera_horario: false });
    // Después de enviar se abre el detalle.
    expect(await screen.findByRole("heading", { name: "Entrega de uniformes" })).toBeInTheDocument();
  });

  it("fuera de horario: 409 abre el diálogo y confirmar reenvía con confirmar_fuera_horario", async () => {
    let intentos = 0;
    const llamadas = api({
      "POST /api/v1/notificaciones/9/confirmar": () => {
        intentos += 1;
        if (intentos === 1) {
          return problema(409, "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION", "Es fuera del horario permitido; confirme para enviar de todos modos.");
        }
        return json({ ...BORRADOR, estado: "ENVIANDO", confirmada_fuera_horario: true }, 202);
      },
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    await user.click(await screen.findByRole("button", { name: "Enviar a 54 colaboradores" }));

    const dialogo = await screen.findByRole("dialog", { name: "Enviar fuera de horario" });
    expect(within(dialogo).getByText(/fuera del horario permitido \(08:00 a 20:00\)/)).toBeInTheDocument();
    expect(llamadas.filter((l) => l.ruta.endsWith("/confirmar"))).toHaveLength(1);
    expect(llamadas.filter((l) => l.ruta.endsWith("/confirmar"))[0]!.cuerpo).toMatchObject({ confirmar_fuera_horario: false });

    await user.click(within(dialogo).getByRole("button", { name: "Sí, enviar ahora" }));
    await waitFor(() => expect(llamadas.filter((l) => l.ruta.endsWith("/confirmar"))).toHaveLength(2));
    expect(llamadas.filter((l) => l.ruta.endsWith("/confirmar"))[1]!.cuerpo).toMatchObject({ modo_envio: "AHORA", confirmar_fuera_horario: true });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("cancelar el diálogo de fuera de horario no reenvía", async () => {
    const llamadas = api({
      "POST /api/v1/notificaciones/9/confirmar": () => problema(409, "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION", "Fuera de horario"),
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    await user.click(await screen.findByRole("button", { name: "Enviar a 54 colaboradores" }));
    const dialogo = await screen.findByRole("dialog");
    await user.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(llamadas.filter((l) => l.ruta.endsWith("/confirmar"))).toHaveLength(1);
  });

  it("programar: valida el horario en pantalla y manda la fecha con la zona de México", async () => {
    const llamadas = api();
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    await screen.findByRole("button", { name: "Enviar a 54 colaboradores" });
    await user.click(screen.getByRole("radio", { name: "Programar" }));
    const programar = screen.getByRole("button", { name: "Programar para 54 colaboradores" });

    await user.click(programar);
    expect(await screen.findByText("Elige fecha y hora de envío.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Fecha de envío"), { target: { value: "2099-01-01" } });
    fireEvent.change(screen.getByLabelText("Hora de envío"), { target: { value: "21:30" } });
    await user.click(programar);
    expect(await screen.findByText("La hora programada está fuera del horario de envío permitido.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Fecha de envío"), { target: { value: "2020-01-01" } });
    fireEvent.change(screen.getByLabelText("Hora de envío"), { target: { value: "09:00" } });
    await user.click(programar);
    expect(await screen.findByText("La programación debe ser a futuro.")).toBeInTheDocument();
    expect(llamadas.filter((l) => l.ruta.endsWith("/confirmar"))).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("Fecha de envío"), { target: { value: "2099-01-01" } });
    await user.click(programar);
    await waitFor(() => expect(llamadas.filter((l) => l.ruta.endsWith("/confirmar"))).toHaveLength(1));
    expect(llamadas.find((l) => l.ruta.endsWith("/confirmar"))!.cuerpo).toEqual({
      modo_envio: "PROGRAMAR",
      programada_para: "2099-01-01T09:00:00-06:00",
      respaldo_correo: false,
      confirmar_fuera_horario: false,
    });
  });

  it("errores del servidor al confirmar: la programación fuera de horario se muestra en su campo", async () => {
    api({
      "POST /api/v1/notificaciones/9/confirmar": () =>
        problema(422, "FUERA_DE_HORARIO", "Fuera de horario", [
          { campo: "programada_para", codigo: "FUERA_DE_HORARIO", mensaje: "La hora queda fuera del horario permitido; ajústela." },
        ]),
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    await screen.findByRole("button", { name: "Enviar a 54 colaboradores" });
    await user.click(screen.getByRole("radio", { name: "Programar" }));
    fireEvent.change(screen.getByLabelText("Fecha de envío"), { target: { value: "2099-01-01" } });
    fireEvent.change(screen.getByLabelText("Hora de envío"), { target: { value: "09:00" } });
    await user.click(screen.getByRole("button", { name: "Programar para 54 colaboradores" }));
    expect(await screen.findByText("La hora queda fuera del horario permitido; ajústela.")).toBeInTheDocument();
  });

  it("un error general del servidor al confirmar se muestra en español", async () => {
    api({
      "POST /api/v1/notificaciones/9/confirmar": () =>
        problema(422, "SIN_DESTINATARIOS_VALIDOS", "No hay destinatarios válidos.", [
          { campo: "notificacion", codigo: "SIN_DESTINATARIOS_VALIDOS", mensaje: "No hay destinatarios válidos." },
        ]),
    });
    const user = userEvent.setup();
    montar();
    await completar(user);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    await user.click(await screen.findByRole("button", { name: "Enviar a 54 colaboradores" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No hay destinatarios válidos. Ajusta la audiencia.");
  });
});

describe("edición de un borrador", () => {
  it("carga el borrador y lo guarda con PATCH", async () => {
    const llamadas = api({
      "GET /api/v1/notificaciones/9": {
        ...BORRADOR,
        modo: "CRITERIOS",
        audiencia_id: null,
        criterios: { op: "O", items: [{ campo: "planta_id", operador: "es", valor: 1 }, { campo: "antiguedad_anios", operador: ">=", valor: 5 }] },
        variables: { "1": { origen: "COLABORADOR", campo: "nombre_completo" }, "2": { origen: "FIJO", valor: "13 nov" } },
        plantilla: { id: 5, nombre: "recordatorio_uniformes_v1", estado_meta: "APROBADA" },
      },
    });
    montar("/notificaciones/9/editar");
    expect(await screen.findByRole("heading", { name: "Editar notificación" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Título del envío")).toHaveValue("Entrega de uniformes"));
    await waitFor(() => expect(screen.getByLabelText("Valor 2")).toHaveValue(5));
    expect(screen.getByLabelText("Valor fijo de {{2}}")).toHaveValue("13 nov");
    expect(screen.getByRole("button", { name: "Combinador: O (cualquiera). Cambiar" })).toBeInTheDocument();
    await userEvent.click(guardar());
    await waitFor(() => expect(ultima(llamadas, "PATCH", "/api/v1/notificaciones/9")).toBeDefined());
    expect(ultima(llamadas, "PATCH", "/api/v1/notificaciones/9")!.cuerpo).toMatchObject({
      modo: "CRITERIOS",
      criterios: { op: "O", items: [{ campo: "planta_id", operador: "es", valor: 1 }, { campo: "antiguedad_anios", operador: ">=", valor: 5 }] },
    });
  });

  it("una notificación que ya no es borrador se abre en su detalle", async () => {
    api({ "GET /api/v1/notificaciones/9": { ...BORRADOR, estado: "COMPLETADA" } });
    montar("/notificaciones/9/editar");
    expect(await screen.findByText(/Resultado del envío/)).toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("la nueva notificación (formulario y embudo) no tiene violaciones críticas ni serias de axe", async () => {
    api();
    const user = userEvent.setup();
    const { container } = montar();
    await completar(user);
    await esperarAccesible(container);
    await user.click(screen.getByRole("button", { name: "Revisar y enviar" }));
    await screen.findByRole("list", { name: "Embudo de la audiencia" });
    await esperarAccesible(container);
  });
});
