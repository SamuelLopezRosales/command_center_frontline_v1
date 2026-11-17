import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { authSimulado, renderizar, USUARIO_PRUEBA } from "@/test/ayudantes";
import type { Conversacion, Mensaje } from "./api";
import { RutasChat } from "./RutasChat";
import { json, problema, simulador } from "./test/simulador";
import { esperarAccesible } from "@/test/axe";

afterEach(() => vi.unstubAllGlobals());

const hace = (horas: number) => new Date(Date.now() - horas * 3600_000).toISOString();

const conv = (sobre: Partial<Conversacion>): Conversacion => ({
  id: 1,
  colaborador_id: 10,
  colaborador_nombre: "Ana Ramírez",
  estado: "ACTIVA",
  origen: "NOTIFICACION",
  verificada: true,
  ventana_abierta: true,
  ultimo_mensaje_entrante_at: hace(5),
  fecha_ultimo_mensaje: hace(5),
  asignada_a_usuario_id: null,
  fecha_asignacion: null,
  ultima_notificacion_id: 3,
  ...sobre,
});

const ABIERTA = conv({ id: 1 });
const CERRADA = conv({ id: 2, colaborador_id: 11, colaborador_nombre: "Miguel Herrera", ventana_abierta: false, ultimo_mensaje_entrante_at: hace(30), asignada_a_usuario_id: 1 });

const mensaje = (sobre: Partial<Mensaje>): Mensaje => ({
  id: 1,
  direccion: "ENTRANTE",
  tipo: "TEXTO",
  plantilla: null,
  contenido: "Hola",
  estado: "RECIBIDO",
  origen_tipo: "BOT",
  enviado_por_usuario_id: null,
  fecha_hora: hace(5),
  error_codigo: null,
  ...sobre,
});

// La API entrega primero el mensaje más reciente.
const MENSAJES = { items: [mensaje({ id: 2, direccion: "SALIENTE", contenido: "Con gusto, ya lo reviso", estado: "ENTREGADO", fecha_hora: hace(4) }), mensaje({ id: 1, contenido: "Necesito mi constancia" })], siguiente: null };

const PLANTILLA = {
  id: 7,
  nombre: "aviso_nomina",
  categoria: "UTILITY",
  idioma: "es_MX",
  estado_meta: "APROBADA",
  texto_con_variables: "Hola {{1}}, tu recibo de {{2}} ya está disponible.",
  ejemplos: [],
  creada_por_usuario_id: 1,
  fecha_creacion: hace(100),
  id_plantilla_meta: "x",
  motivo_rechazo: null,
};

const USUARIOS = {
  items: [
    { id: 1, nombre: "David Bet", correo: "david@empresa.com", rol: "RH", activo: true, ultima_actividad: null, fecha_creacion: hace(100) },
    { id: 2, nombre: "Lucía Mora", correo: "lucia@empresa.com", rol: "RH", activo: true, ultima_actividad: null, fecha_creacion: hace(100) },
  ],
};

const yo = (permisos = ["chat:responder", "usuarios:administrar"]) => ({ ...USUARIO_PRUEBA, permisos });

function montar() {
  return renderizar(
    <Routes>
      <Route path="chat/*" element={<RutasChat />} />
    </Routes>,
    { ruta: "/chat", auth: authSimulado({ haySesion: async () => true }) },
  );
}

const base = (extra: Record<string, unknown> = {}) => ({
  "GET /api/v1/usuarios/yo": yo(),
  "POST /api/v1/sesion/iniciar": () => new Response(null, { status: 204 }),
  "GET /api/v1/conversaciones": { items: [ABIERTA, CERRADA], siguiente: null },
  "GET /api/v1/conversaciones/1/mensajes": MENSAJES,
  "GET /api/v1/conversaciones/2/mensajes": { items: [], siguiente: null },
  "GET /api/v1/plantillas-mensaje": { items: [PLANTILLA], siguiente: null },
  "GET /api/v1/usuarios": USUARIOS,
  ...extra,
});

describe("chat de RH: lista de conversaciones (WAP-01)", () => {
  it("muestra la ventana abierta con el tiempo restante, la cerrada y la asignación", async () => {
    simulador(base());
    montar();
    const ana = (await screen.findByText("Ana Ramírez")).closest("button")!;
    const miguel = screen.getByText("Miguel Herrera").closest("button")!;
    expect(within(ana).getByText("Ventana abierta")).toBeInTheDocument();
    expect(within(ana).getByText(/^Quedan 1[89] h \d+ min$/)).toBeInTheDocument();
    expect(within(ana).getByText("Sin asignar")).toBeInTheDocument();
    expect(within(miguel).getByText("Ventana cerrada")).toBeInTheDocument();
    // El usuario 1 es la persona en sesión.
    expect(within(miguel).getByText("Asignada a ti")).toBeInTheDocument();
    expect(screen.getByText("Pantalla pendiente de validación visual con Samuel.")).toBeInTheDocument();
  });

  it("filtra por estado, por mis asignadas y por notificación con los parámetros de la API", async () => {
    const llamadas = simulador(base());
    montar();
    await screen.findByText("Ana Ramírez");
    await userEvent.selectOptions(screen.getByLabelText("Estado"), "ACTIVA");
    await userEvent.click(screen.getByLabelText("Asignadas a mí"));
    await userEvent.type(screen.getByLabelText("Notificación"), "3");
    await waitFor(() => {
      const ultima = llamadas.filter((l) => l.ruta === "/api/v1/conversaciones").at(-1)!;
      expect(ultima.url).toContain("estado=ACTIVA");
      expect(ultima.url).toContain("asignada_a=1");
      expect(ultima.url).toContain("notificacion_id=3");
    });
  });

  it("sin el permiso chat:responder no consulta conversaciones", async () => {
    const llamadas = simulador(base({ "GET /api/v1/usuarios/yo": yo(["colaboradores:ver"]) }));
    montar();
    expect(await screen.findByText("No tienes permiso para usar el chat de RH.")).toBeInTheDocument();
    expect(llamadas.some((l) => l.ruta === "/api/v1/conversaciones")).toBe(false);
  });
});

describe("chat de RH: detalle y envío (WAP-02 a 04)", () => {
  it("muestra el hilo y envía texto libre con la ventana abierta", async () => {
    const llamadas = simulador(base({ "POST /api/v1/conversaciones/1/mensajes": () => json({ mensaje_id: 9 }, 202) }));
    montar();
    await userEvent.click((await screen.findByText("Ana Ramírez")).closest("button")!);
    const hilo = await screen.findByRole("list", { name: "Mensajes de la conversación" });
    const textos = within(hilo).getAllByRole("listitem").map((li) => li.textContent);
    // Se lee de arriba abajo: primero el más antiguo.
    expect(textos[0]).toContain("Necesito mi constancia");
    expect(textos[1]).toContain("Con gusto, ya lo reviso");
    expect(screen.queryByLabelText("Plantilla aprobada")).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Mensaje"), "Listo, te la envío hoy");
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText("Mensaje enviado. Se entregará en unos segundos.")).toBeInTheDocument();
    const envio = llamadas.find((l) => l.metodo === "POST" && l.ruta === "/api/v1/conversaciones/1/mensajes")!;
    expect(envio.cuerpo).toEqual({ texto: "Listo, te la envío hoy" });
  });

  it("con la ventana cerrada no ofrece texto libre: solo plantilla aprobada, con sus variables", async () => {
    const llamadas = simulador(base({ "POST /api/v1/conversaciones/2/mensajes/plantilla": () => json({ mensaje_id: 4 }, 202) }));
    montar();
    await userEvent.click((await screen.findByText("Miguel Herrera")).closest("button")!);
    expect(await screen.findByText("La ventana de 24 horas está cerrada")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mensaje")).not.toBeInTheDocument();
    expect(llamadas.some((l) => l.metodo === "POST" && l.ruta.endsWith("/mensajes"))).toBe(false);

    await userEvent.selectOptions(await screen.findByLabelText("Plantilla aprobada"), "7");
    await userEvent.click(screen.getByRole("button", { name: "Enviar plantilla" }));
    expect(await screen.findByText("Completa todas las variables de la plantilla.")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Variable {{1}}"), "Miguel");
    await userEvent.type(screen.getByLabelText("Variable {{2}}"), "noviembre");
    expect(screen.getByLabelText("Vista previa")).toHaveTextContent("Hola Miguel, tu recibo de noviembre ya está disponible.");
    await userEvent.click(screen.getByRole("button", { name: "Enviar plantilla" }));
    await screen.findByText("Mensaje enviado. Se entregará en unos segundos.");
    const envio = llamadas.find((l) => l.ruta === "/api/v1/conversaciones/2/mensajes/plantilla")!;
    expect(envio.cuerpo).toEqual({ plantilla_mensaje_id: 7, variables: ["Miguel", "noviembre"] });
    expect(llamadas.filter((l) => l.metodo === "GET" && l.ruta === "/api/v1/plantillas-mensaje")[0]!.url).toContain("estado=APROBADA");
  });

  it("una plantilla con nombre pide una variable por nombre y la manda en variables_nombradas", async () => {
    const NOMBRADA = {
      ...PLANTILLA,
      id: 9,
      nombre: "vida_aviso_checkout",
      texto_con_variables: "Hola {{guest_name}}, tu salida es a las {{checkout_time}}. Adiós {{guest_name}}.",
    };
    const llamadas = simulador(
      base({
        "GET /api/v1/plantillas-mensaje": { items: [PLANTILLA, NOMBRADA], siguiente: null },
        "POST /api/v1/conversaciones/2/mensajes/plantilla": () => json({ mensaje_id: 4 }, 202),
      }),
    );
    montar();
    await userEvent.click((await screen.findByText("Miguel Herrera")).closest("button")!);
    await userEvent.selectOptions(await screen.findByLabelText("Plantilla aprobada"), "9");
    // Una fila por nombre (guest_name aparece dos veces en el texto y cuenta una).
    expect(screen.getAllByLabelText(/^Variable \{\{/)).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Enviar plantilla" }));
    expect(await screen.findByText("Completa todas las variables de la plantilla.")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Variable {{guest_name}}"), "Miguel");
    await userEvent.type(screen.getByLabelText("Variable {{checkout_time}}"), "12:00");
    expect(screen.getByLabelText("Vista previa")).toHaveTextContent("Hola Miguel, tu salida es a las 12:00. Adiós Miguel.");
    await userEvent.click(screen.getByRole("button", { name: "Enviar plantilla" }));
    await screen.findByText("Mensaje enviado. Se entregará en unos segundos.");
    const envio = llamadas.find((l) => l.ruta === "/api/v1/conversaciones/2/mensajes/plantilla")!;
    expect(envio.cuerpo).toEqual({ plantilla_mensaje_id: 9, variables_nombradas: { guest_name: "Miguel", checkout_time: "12:00" } });
  });

  it("si el servidor responde 409 VENTANA_24H_CERRADA la pantalla pasa a modo plantilla y lo explica", async () => {
    simulador(
      base({
        "POST /api/v1/conversaciones/1/mensajes": () => problema(409, "VENTANA_24H_CERRADA", "La ventana de 24 horas está cerrada: solo puede enviar una plantilla aprobada."),
      }),
    );
    montar();
    await userEvent.click((await screen.findByText("Ana Ramírez")).closest("button")!);
    await userEvent.type(await screen.findByLabelText("Mensaje"), "Hola de nuevo");
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText("El servidor indica que la ventana de 24 horas ya se cerró. Envía una plantilla aprobada.")).toBeInTheDocument();
    expect(await screen.findByLabelText("Plantilla aprobada")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mensaje")).not.toBeInTheDocument();
    // No se muestra un error genérico.
    expect(screen.queryByText("No se pudo enviar el mensaje. Intenta de nuevo.")).not.toBeInTheDocument();
    // La ficha de Ana ahora marca la ventana como cerrada (también la lista, tras refrescar).
    expect(screen.getAllByText("Ventana cerrada").length).toBeGreaterThanOrEqual(2);
  });

  it("un error distinto en el envío sí se muestra como error", async () => {
    simulador(base({ "POST /api/v1/conversaciones/1/mensajes": () => problema(500, "ERROR_INTERNO", "Fallo del servidor") }));
    montar();
    await userEvent.click((await screen.findByText("Ana Ramírez")).closest("button")!);
    await userEvent.type(await screen.findByLabelText("Mensaje"), "Hola");
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fallo del servidor");
    expect(screen.getByLabelText("Mensaje")).toBeInTheDocument();
  });
});

describe("chat de RH: asignación (WAP-05)", () => {
  it("asigna a la persona elegida y refresca la lista", async () => {
    const llamadas = simulador(base({ "PUT /api/v1/conversaciones/1/asignacion": () => json({ ...ABIERTA, asignada_a_usuario_id: 2 }) }));
    montar();
    await userEvent.click((await screen.findByText("Ana Ramírez")).closest("button")!);
    await userEvent.selectOptions(await screen.findByLabelText("Asignar a"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Asignar" }));
    expect(await screen.findByText("Conversación asignada.")).toBeInTheDocument();
    expect(llamadas.find((l) => l.metodo === "PUT")!.cuerpo).toEqual({ usuario_id: 2 });
    await waitFor(() => expect(llamadas.filter((l) => l.ruta === "/api/v1/conversaciones").length).toBeGreaterThan(1));
  });

  it("422 (el usuario no existe o es de otra empresa) se explica sin dejar la pantalla", async () => {
    simulador(
      base({
        "PUT /api/v1/conversaciones/1/asignacion": () => problema(422, "USUARIO_NO_ENCONTRADO", "Datos no válidos", [{ campo: "usuario_id", codigo: "NO_ENCONTRADO", mensaje: "El usuario no existe." }]),
      }),
    );
    montar();
    await userEvent.click((await screen.findByText("Ana Ramírez")).closest("button")!);
    await userEvent.click(await screen.findByRole("button", { name: "Asignarme" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El usuario no existe o no pertenece a tu empresa.");
    expect(screen.getByRole("list", { name: "Mensajes de la conversación" })).toBeInTheDocument();
  });
});

describe("accesibilidad (CC-NFR-012)", () => {
  it("el chat (lista y detalle con ventana abierta y cerrada) no tiene violaciones críticas ni serias de axe", async () => {
    simulador(base());
    const { container } = montar();
    const ana = (await screen.findByText("Ana Ramírez")).closest("button")!;
    await esperarAccesible(container);
    await userEvent.click(ana);
    await screen.findByRole("list", { name: "Mensajes de la conversación" });
    await esperarAccesible(container);
    await userEvent.click(screen.getByText("Miguel Herrera").closest("button")!);
    await screen.findByText("La ventana de 24 horas está cerrada");
    await esperarAccesible(container);
  });
});
