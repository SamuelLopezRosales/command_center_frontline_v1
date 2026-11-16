import { expect, iniciarSesion, SUFIJO, test, vigilarErroresApi } from "./base";
import type { Page } from "@playwright/test";

/** Llena la parte común: título, criterio (estatus ACTIVO), plantilla aprobada `aviso_general` y su variable. */
async function llenarNotificacion(page: Page, titulo: string) {
  await page.goto("/notificaciones/nueva");
  await expect(page.getByRole("heading", { name: "Nueva notificación" })).toBeVisible();
  await page.getByLabel("Título del envío").fill(titulo);

  // Criterio: estatus = ACTIVO (los catálogos se llenan con la API).
  const campo = page.getByLabel("Campo 1");
  await expect(campo.locator("option")).not.toHaveCount(1);
  await campo.selectOption("estatus");
  await page.getByLabel("Valor 1").selectOption("ACTIVO");

  const plantilla = page.getByLabel("Plantilla", { exact: true });
  await expect(plantilla.getByRole("option", { name: /aviso_general/ }), "la plantilla aprobada aviso_general debe existir en el stack local").toBeAttached();
  await plantilla.selectOption({ label: (await plantilla.getByRole("option", { name: /aviso_general/ }).textContent())!.trim() });
  await page.getByLabel("Campo de {{1}}").selectOption("nombre_completo");
}

test.describe("6. Notificación con embudo", () => {
  test("arma la audiencia por criterios, revisa el embudo con excluidos y envía", async ({ page }) => {
    const verificar = vigilarErroresApi(page);
    const titulo = `Aviso E2E ${SUFIJO}`;
    await iniciarSesion(page);
    await llenarNotificacion(page, titulo);

    await page.getByRole("button", { name: "Revisar y enviar" }).click();
    const embudo = page.getByRole("list", { name: "Embudo de la audiencia" });
    await expect(embudo, "debió mostrarse el embudo tras revisar la audiencia").toBeVisible();
    const etapas = await embudo.getByRole("listitem").allTextContents();
    expect(etapas).toHaveLength(4);
    const cifras = etapas.map((t) => Number(/(\d+)$/.exec(t.trim())![1]));
    for (let i = 1; i < cifras.length; i++) expect(cifras[i]!, `el embudo no puede crecer: ${etapas.join(" | ")}`).toBeLessThanOrEqual(cifras[i - 1]!);
    // El stack local trae colaboradores sin consentimiento: hay excluidos y se explican.
    expect(cifras[0]! - cifras[3]!, "debería haber excluidos (colaboradores sin consentimiento)").toBeGreaterThan(0);
    await expect(page.getByText(/excluidos: .*sin consentimiento/)).toBeVisible();
    await expect(page.getByText("Se omiten automáticamente y quedan registrados.")).toBeVisible();

    await page.getByRole("button", { name: `Enviar a ${cifras[3]} colaboradores` }).click();
    // Si la hora local queda fuera del horario permitido se pide confirmar.
    const fuera = page.getByRole("dialog", { name: "Enviar fuera de horario" });
    if (await fuera.isVisible({ timeout: 1500 }).catch(() => false)) await fuera.getByRole("button", { name: "Sí, enviar ahora" }).click();

    // Detalle del envío: sin Lambdas puede quedarse en «Enviando».
    await expect(page.getByRole("heading", { name: titulo }), "tras enviar debe abrirse el detalle del envío").toBeVisible();
    await expect(page.getByRole("heading", { name: "Resultado del envío" })).toBeVisible();
    await expect(page.getByText(/Enviando|Completado|Con fallas/).first()).toBeVisible();
    await expect(page.getByText(/sin consentimiento/i).first()).toBeVisible();

    // Aparece en el listado de envíos.
    await page.goto("/notificaciones");
    await expect(page.getByRole("row").filter({ hasText: titulo })).toBeVisible();
    verificar();
  });

  test("programa el envío para mañana y queda en Programadas", async ({ page }) => {
    const verificar = vigilarErroresApi(page);
    const titulo = `Aviso programado E2E ${SUFIJO}`;
    await iniciarSesion(page);
    await llenarNotificacion(page, titulo);

    await page.getByRole("radio", { name: "Programar" }).check();
    const manana = new Date(Date.now() + 36 * 3600_000).toLocaleDateString("en-CA", { timeZone: "America/Mexico_City" });
    await page.getByLabel("Fecha de envío").fill(manana);
    await page.getByLabel("Hora de envío").fill("10:00");
    await page.getByRole("button", { name: "Revisar y enviar" }).click();
    await expect(page.getByRole("list", { name: "Embudo de la audiencia" })).toBeVisible();
    await page.getByRole("button", { name: /^Programar para \d+ colaboradores?$/ }).click();

    await expect(page.getByRole("heading", { name: titulo })).toBeVisible();
    await expect(page.getByText(/Programada para \d+ \w+, 10:00/)).toBeVisible();

    await page.goto("/notificaciones");
    await page.getByRole("tab", { name: /Programadas/ }).click();
    await expect(page.getByRole("row").filter({ hasText: titulo })).toBeVisible();

    // Limpieza: se cancela para no dejar un envío programado que nunca saldrá (no hay Scheduler local).
    await page.getByRole("row").filter({ hasText: titulo }).getByRole("link", { name: /Ver detalle/ }).click();
    await page.getByRole("button", { name: "Cancelar envío" }).click();
    await page.getByRole("dialog", { name: "Cancelar notificación" }).getByRole("button", { name: "Sí, cancelar" }).click();
    await expect(page.getByText("Cancelado").first()).toBeVisible();
    verificar();
  });

  test("el catálogo muestra la plantilla aprobada aviso_general", async ({ page }) => {
    await iniciarSesion(page);
    await page.goto("/notificaciones/plantillas");
    const fila = page.getByRole("row").filter({ hasText: "aviso_general" });
    await expect(fila).toContainText("Aprobada");
    await expect(fila).toContainText("1 variable");
  });
});
