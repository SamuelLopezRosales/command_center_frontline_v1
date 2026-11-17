import { configure, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { listadoCampos, ORGS, PLANTAS } from "@/test/fixturas220";
import { renderizar } from "@/test/ayudantes";
import { RutasNotificaciones } from "../RutasNotificaciones";
import { destinatario, json, notificacion, plantillaMensaje, problema, simulador } from "../test/datos";
import { esperarAccesible } from "@/test/axe";

// Las pruebas con muchos pasos de usuario tardan más que el límite por defecto.
vi.setConfig({ testTimeout: 20000 });
configure({ asyncUtilTimeout: 8000 });

afterEach(() => vi.unstubAllGlobals());

type Rutas = Parameters<typeof simulador>[0];

const DESTINATARIOS = [
  destinatario(),
  destinatario({ id: 2, nombre: "Samuel López Rosales", celular_enmascarado: "+52 •• •••• 1290", estado: "ENTREGADO", conversacion_id: null, fecha_estado: "2026-11-12T22:01:00Z" }),
  destinatario({
    id: 3,
    nombre: "Miguel Ángel Herrera Cruz",
    planta: "Monterrey",
    celular_enmascarado: "+52 •• •••• 4411",
    estado: "FALLIDO",
    motivo_fallo: "Número sin WhatsApp",
    conversacion_id: null,
    fecha_estado: "2026-11-12T22:03:00Z",
  }),
  destinatario({ id: 4, nombre: "Jorge Luis Medina Paredes", estado: "RESPONDIO", celular_enmascarado: "+52 •• •••• 6604", fecha_estado: "2026-11-12T22:12:00Z" }),
  destinatario({ id: 5, nombre: "Laura Pérez", estado: "EXCLUIDO", motivo_exclusion: "SIN_CONSENTIMIENTO", celular_enmascarado: null, canal_usado: null, conversacion_id: null }),
  destinatario({ id: 6, nombre: "Carlos Ruiz", estado: "EXCLUIDO", motivo_exclusion: "SIN_CONSENTIMIENTO", celular_enmascarado: null, canal_usado: null, conversacion_id: null }),
  destinatario({ id: 7, nombre: "Rosa Díaz", estado: "EXCLUIDO", motivo_exclusion: "ESTATUS_BAJA", celular_enmascarado: null, canal_usado: null, conversacion_id: null }),
];

const CON_FALLAS = notificacion({
  estado: "CON_FALLAS",
  contadores: { seleccionados: 118, excluidos: 6, validos: 112, enviados: 112, entregados: 108, leidos: 84, respondieron: 7, fallidos: 1 },
});

function api(extra: Rutas = {}) {
  return simulador({
    "GET /api/v1/campos": listadoCampos(),
    "GET /api/v1/organizaciones": { items: ORGS },
    "GET /api/v1/plantas": { items: PLANTAS },
    "GET /api/v1/plantillas-mensaje": { items: [plantillaMensaje()], siguiente: null },
    "GET /api/v1/audiencias": { items: [], siguiente: null },
    "GET /api/v1/notificaciones/1": CON_FALLAS,
    "GET /api/v1/notificaciones/1/destinatarios": { items: DESTINATARIOS, siguiente: null },
    ...extra,
  });
}

const montar = (ruta = "/notificaciones/1") =>
  renderizar(
    <Routes>
      <Route path="notificaciones/*" element={<RutasNotificaciones />} />
    </Routes>,
    { ruta },
  );

describe("detalle de envío (cv1_10)", () => {
  it("muestra el resultado, los excluidos por motivo y el mensaje enviado", async () => {
    api();
    montar();
    expect(await screen.findByRole("heading", { name: "Aviso de cierre de nómina" })).toBeInTheDocument();
    const resultado = screen.getByRole("heading", { name: "Resultado del envío" }).closest("section")!;
    const filas = within(resultado).getAllByRole("listitem").map((f) => f.textContent);
    expect(filas).toEqual(["Seleccionados118", "Enviados112", "Entregados108", "Leídos84", "Fallidos1"]);
    expect(await within(resultado).findByText("6 excluidos antes del envío: 2 sin consentimiento y 1 con estatus BAJA.")).toBeInTheDocument();

    expect(screen.getByText("Hola {{nombre_completo}}, el cierre de nómina de la quincena es hoy 12 nov.")).toBeInTheDocument();
    expect(screen.getByText("Plantilla: aviso_nomina_v2 · APROBADA por Meta")).toBeInTheDocument();
    expect(screen.getByText("7 respuestas")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver conversaciones →" })).toHaveAttribute("href", "/chat");
    // La fecha de envío se muestra en la zona de México.
    expect(screen.getByText(/Detalle · enviado 12 nov, 16:00/)).toBeInTheDocument();
  });

  it("lista los destinatarios con el celular enmascarado, su estado y la hora local", async () => {
    api();
    montar();
    const tabla = await screen.findByRole("table", { name: "Destinatarios" });
    const filas = within(tabla).getAllByRole("row").slice(1);
    const ana = within(filas[0]!);
    expect(ana.getByText("Ana Lucía Ramírez Torres")).toBeInTheDocument();
    expect(ana.getByText("Apodaca")).toBeInTheDocument();
    expect(ana.getByText("+52 •• •••• 5678")).toBeInTheDocument();
    expect(ana.getByText("Leído")).toBeInTheDocument();
    expect(ana.getByText("16:02")).toBeInTheDocument();
    expect(ana.getByRole("link", { name: "Ver chat: Ana Lucía Ramírez Torres" })).toBeInTheDocument();

    expect(within(filas[1]!).getByText("Entregado")).toBeInTheDocument();
    expect(within(filas[2]!).getByText("Fallido")).toBeInTheDocument();
    expect(within(filas[2]!).getByText("Número sin WhatsApp")).toBeInTheDocument();
    expect(within(filas[3]!).getByText("Respondió")).toBeInTheDocument();
    expect(within(filas[4]!).getByText("Excluido")).toBeInTheDocument();

    // Nunca aparece un celular completo: solo la máscara que manda la API.
    expect(tabla.textContent).not.toMatch(/\d{10}/);
    expect(tabla.textContent).not.toMatch(/\+52\d/);
  });

  it("muestra la audiencia por criterios con etiquetas legibles y la línea de tiempo", async () => {
    api({
      "GET /api/v1/notificaciones/1": notificacion({
        modo: "CRITERIOS",
        audiencia_id: null,
        audiencia_nombre: null,
        criterios: {
          op: "Y",
          items: [
            { campo: "planta_id", operador: "es", valor: 1 },
            { campo: "tipo_empleado", operador: "es", valor: "OPERATIVO" },
            { campo: "antiguedad_anios", operador: ">=", valor: 5 },
          ],
        },
      }),
    });
    montar();
    const audiencia = (await screen.findByRole("heading", { name: "Audiencia" })).closest("section")!;
    await waitFor(() => expect(within(audiencia).getByText("Planta: es Apodaca")).toBeInTheDocument());
    expect(within(audiencia).getByText("Tipo de empleado: es Operativo")).toBeInTheDocument();
    expect(within(audiencia).getByText("Antigüedad (años): ≥ 5 años")).toBeInTheDocument();
    expect(within(audiencia).getByText("Consentimiento: sí (automático)")).toBeInTheDocument();

    const linea = screen.getByRole("heading", { name: "Línea de tiempo" }).closest("section")!;
    expect(within(linea).getByText("15:50")).toBeInTheDocument();
    expect(within(linea).getByText("Creada")).toBeInTheDocument();
    expect(within(linea).getByText("Enviada: 112/112")).toBeInTheDocument();
  });

  it("reintenta los fallidos y refresca el detalle", async () => {
    let reintentada = false;
    const llamadas = api({
      "GET /api/v1/notificaciones/1": () => json(reintentada ? { ...CON_FALLAS, estado: "ENVIANDO" } : CON_FALLAS),
      "POST /api/v1/notificaciones/1/reintentar": () => {
        reintentada = true;
        return json({ ...CON_FALLAS, estado: "ENVIANDO" }, 202);
      },
    });
    const user = userEvent.setup();
    montar();
    await user.click(await screen.findByRole("button", { name: "Reintentar fallidos (1)" }));
    expect(await screen.findByText("Reintento en curso para los destinatarios fallidos.")).toBeInTheDocument();
    const llamada = llamadas.find((l) => l.ruta.endsWith("/reintentar"))!;
    expect(llamada.cuerpo).toEqual({ confirmar_fuera_horario: false });
    // Ya no está CON_FALLAS: el botón desaparece.
    await waitFor(() => expect(screen.queryByRole("button", { name: /Reintentar fallidos/ })).not.toBeInTheDocument());
  });

  it("reintentar fuera de horario pide confirmación y reenvía con confirmar_fuera_horario", async () => {
    let intentos = 0;
    const llamadas = api({
      "POST /api/v1/notificaciones/1/reintentar": () => {
        intentos += 1;
        return intentos === 1
          ? problema(409, "FUERA_DE_HORARIO_REQUIERE_CONFIRMACION", "Fuera de horario")
          : json({ ...CON_FALLAS, estado: "ENVIANDO" }, 202);
      },
    });
    const user = userEvent.setup();
    montar();
    await user.click(await screen.findByRole("button", { name: "Reintentar fallidos (1)" }));
    const dialogo = await screen.findByRole("dialog", { name: "Reintentar fuera de horario" });
    await user.click(within(dialogo).getByRole("button", { name: "Sí, reintentar" }));
    await waitFor(() => expect(llamadas.filter((l) => l.ruta.endsWith("/reintentar"))).toHaveLength(2));
    expect(llamadas.filter((l) => l.ruta.endsWith("/reintentar"))[1]!.cuerpo).toEqual({ confirmar_fuera_horario: true });
    expect(await screen.findByText("Reintento en curso para los destinatarios fallidos.")).toBeInTheDocument();
  });

  it("avisa cuando ningún fallido se puede reintentar", async () => {
    api({
      "POST /api/v1/notificaciones/1/reintentar": () =>
        problema(422, "SIN_FALLIDOS_REINTENTABLES", "No hay destinatarios fallidos que se puedan reintentar."),
    });
    const user = userEvent.setup();
    montar();
    await user.click(await screen.findByRole("button", { name: "Reintentar fallidos (1)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ningún fallido se puede reintentar hoy");
  });

  it("no ofrece reintentar si el envío no tiene fallas", async () => {
    api({ "GET /api/v1/notificaciones/1": notificacion() });
    montar();
    await screen.findByRole("heading", { name: "Aviso de cierre de nómina" });
    expect(screen.queryByRole("button", { name: /Reintentar fallidos/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar envío" })).not.toBeInTheDocument();
  });

  it("duplica el envío como borrador y abre su edición", async () => {
    const llamadas = api({
      "POST /api/v1/notificaciones/1/duplicar": () => json(notificacion({ id: 10, estado: "BORRADOR", titulo: "Aviso de cierre de nómina (copia)", fecha_envio: null }), 201),
      "GET /api/v1/notificaciones/10": notificacion({ id: 10, estado: "BORRADOR", titulo: "Aviso de cierre de nómina (copia)", fecha_envio: null, modo: "GRUPO" }),
    });
    const user = userEvent.setup();
    montar();
    await user.click(await screen.findByRole("button", { name: "Duplicar envío" }));
    expect(await screen.findByRole("heading", { name: "Editar notificación" })).toBeInTheDocument();
    expect(llamadas.filter((l) => l.metodo === "POST" && l.ruta.endsWith("/1/duplicar"))).toHaveLength(1);
    await waitFor(() => expect(screen.getByLabelText("Título del envío")).toHaveValue("Aviso de cierre de nómina (copia)"));
  });

  it("cancela una notificación programada tras confirmar", async () => {
    const programada = notificacion({ estado: "PROGRAMADA", fecha_envio: null, programada_para: "2026-11-16T14:00:00Z" });
    const llamadas = api({
      "GET /api/v1/notificaciones/1": programada,
      "POST /api/v1/notificaciones/1/cancelar": () => json({ ...programada, estado: "CANCELADA" }),
    });
    const user = userEvent.setup();
    montar();
    expect(await screen.findByText("Programada para 16 nov, 08:00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancelar envío" }));
    await user.click(within(screen.getByRole("dialog", { name: "Cancelar notificación" })).getByRole("button", { name: "Sí, cancelar" }));
    expect(await screen.findByText("Notificación cancelada.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST" && l.ruta.endsWith("/cancelar"))).toBe(true);
  });

  it("un envío inexistente muestra el error de la API", async () => {
    api({ "GET /api/v1/notificaciones/1": () => problema(404, "NO_ENCONTRADO", "El recurso no existe.") });
    montar();
    expect(await screen.findByRole("alert")).toHaveTextContent("El recurso no existe.");
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el detalle de envío no tiene violaciones críticas ni serias de axe", async () => {
    api();
    const { container } = montar();
    await screen.findByRole("heading", { name: "Resultado del envío" });
    await screen.findByText("Miguel Ángel Herrera Cruz");
    await esperarAccesible(container);
  });
});

describe("fechas en la zona de México (CC-NFR-014)", () => {
  it("una programación UTC de madrugada se muestra en el día anterior de la Ciudad de México", async () => {
    api({ "GET /api/v1/notificaciones/1": notificacion({ estado: "PROGRAMADA", fecha_envio: null, programada_para: "2026-11-16T03:30:00Z" }) });
    montar();
    expect(await screen.findByText("Programada para 15 nov, 21:30")).toBeInTheDocument();
  });
});

describe("motivos de fallo del envío", () => {
  it("traduce los códigos del enviador y deja tal cual los que no conoce", async () => {
    api({
      "GET /api/v1/notificaciones/1/destinatarios": {
        items: [
          destinatario({ id: 1, nombre: "Ana", estado: "FALLIDO", motivo_fallo: "PLANTILLA_PARAMETROS", conversacion_id: null }),
          destinatario({ id: 2, nombre: "Beto", estado: "FALLIDO", motivo_fallo: "VARIABLE_SIN_VALOR", conversacion_id: null }),
          destinatario({ id: 3, nombre: "Carla", estado: "FALLIDO", motivo_fallo: "OTRO_CODIGO", conversacion_id: null }),
        ],
        siguiente: null,
      },
    });
    montar();
    const tabla = await screen.findByRole("table", { name: "Destinatarios" });
    expect(await within(tabla).findByText(/Meta rechazó los parámetros de la plantilla/)).toBeInTheDocument();
    expect(within(tabla).getByText(/Falta el dato del colaborador/)).toBeInTheDocument();
    expect(within(tabla).getByText("OTRO_CODIGO")).toBeInTheDocument();
  });
});
