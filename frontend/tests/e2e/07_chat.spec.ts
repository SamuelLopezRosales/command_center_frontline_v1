import { envejecerConversacion, escribirComoColaborador, respuestasDelBot } from "./apoyo";
import { altaColaborador, celularUnico, expect, iniciarSesion, SUFIJO, test, vigilarErroresApi } from "./base";

test.describe("7. Chat de RH", () => {
  test("lista las conversaciones con su ventana de 24 h y abre el detalle", async ({ page }) => {
    test.setTimeout(120_000);
    const verificar = vigilarErroresApi(page);
    const celular = celularUnico();
    const waId = `52${celular}`;
    const apellido = `Chat${SUFIJO}`;
    await iniciarSesion(page);
    await altaColaborador(page, { numero: `CH-${SUFIJO}`, nombres: "Lucero", apellido, celular });

    // Una persona escribe «constancia»: nace una conversación con ventana de 24 h abierta.
    escribirComoColaborador(waId, { texto: "constancia" });
    const r = respuestasDelBot(waId, { contiene: "Tu código de verificación es", esperaSeg: 40 });
    expect(r.agotado, "el bot no respondió (¿corre worker-whatsapp?)").toBeUndefined();

    await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Chat" }).click();
    await expect(page.getByRole("heading", { name: "Chat", exact: true })).toBeVisible();
    const conversacion = page.getByRole("button").filter({ hasText: apellido });
    await expect(conversacion, "la conversación nueva debe aparecer en el chat").toBeVisible();
    await expect(conversacion).toContainText("Ventana abierta");
    await expect(conversacion).toContainText(/Quedan 2\d h|Quedan 23 h/);
    await expect(conversacion).toContainText("Sin asignar");

    // Filtros: por estado.
    await page.getByLabel("Estado", { exact: true }).selectOption("CERRADA");
    await expect(conversacion).toHaveCount(0);
    await page.getByLabel("Estado", { exact: true }).selectOption("");
    await expect(conversacion).toBeVisible();

    // Detalle: con la ventana abierta se puede escribir texto libre.
    await conversacion.click();
    await expect(page.getByLabel("Mensaje", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar", exact: true })).toBeVisible();
    verificar();
  });

  test("con la ventana de 24 h cerrada solo se ofrece una plantilla aprobada", async ({ page }) => {
    test.setTimeout(120_000);
    const celular = celularUnico();
    const waId = `52${celular}`;
    const apellido = `Cerrada${SUFIJO}`;
    const numero = `CC-${SUFIJO}`;
    await iniciarSesion(page);
    await altaColaborador(page, { numero, nombres: "Rosa", apellido, celular });
    escribirComoColaborador(waId, { texto: "constancia" });
    expect(respuestasDelBot(waId, { contiene: "Tu código de verificación es", esperaSeg: 40 }).agotado).toBeUndefined();
    // El último mensaje entrante pasa a hace 30 horas: la ventana ya cerró.
    expect(envejecerConversacion(numero).actualizadas).toBe(1);

    await page.goto("/chat");
    const conversacion = page.getByRole("button").filter({ hasText: apellido });
    await expect(conversacion).toContainText("Ventana cerrada");
    await conversacion.click();
    await expect(page.getByText("La ventana de 24 horas está cerrada")).toBeVisible();
    await expect(page.getByLabel("Mensaje", { exact: true }), "con la ventana cerrada no debe haber texto libre").toHaveCount(0);
    await expect(page.getByLabel("Plantilla aprobada")).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar plantilla" })).toBeVisible();
  });
});
