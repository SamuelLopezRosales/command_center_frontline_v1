import { expect, iniciarSesion, SUFIJO, test, vigilarErroresApi } from "./base";

test.describe("4. Publicación de plantilla de constancia", () => {
  test("crea la plantilla, edita el borrador, valida y publica la versión 1", async ({ page }) => {
    const verificar = vigilarErroresApi(page);
    const nombre = `Constancia E2E ${SUFIJO}`;
    await iniciarSesion(page);
    await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Constancias" }).click();
    await page.getByRole("button", { name: "+ Nueva plantilla" }).or(page.getByRole("link", { name: "+ Nueva plantilla" })).click();

    const dialogo = page.getByRole("dialog", { name: "Nueva plantilla" });
    await dialogo.getByLabel("Nombre", { exact: true }).fill(nombre);
    await dialogo.getByLabel("Descripción (opcional)").fill("Plantilla creada por la prueba E2E");
    await dialogo.getByRole("button", { name: "Crear plantilla" }).click();

    // Editor: se escribe texto y se inserta una variable.
    const documento = page.getByRole("textbox", { name: "Contenido de la constancia" });
    await expect(documento, "debió abrirse el editor de la plantilla recién creada").toBeVisible();
    await documento.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("La empresa hace constar que ");
    await page.getByRole("button", { name: "Insertar variable nombre_completo" }).click();
    await page.keyboard.type(" labora con nosotros desde el ");
    await page.getByRole("button", { name: "Insertar variable fecha_ingreso" }).click();
    await page.keyboard.type(".");
    await expect(documento).toContainText("La empresa hace constar que");
    await expect(documento.locator('[data-variable="nombre_completo"]')).toBeVisible();

    await page.getByRole("button", { name: "Guardar borrador" }).click();
    await expect(page.getByText("Borrador guardado.")).toBeVisible();

    // Validación.
    await page.getByRole("button", { name: "Validar", exact: true }).click();
    await expect(page.getByText("Sin errores: todas las variables son válidas.")).toBeVisible();

    // Publicación (puede pedir confirmar el uso de datos sensibles: no con estas variables).
    await page.getByRole("button", { name: /^Publicar v\d+$/ }).click();
    await expect(page.getByText(/Se publicó la versión v1\./)).toBeVisible();

    // Aparece en el listado como activa con su versión.
    await page.getByRole("link", { name: "← Constancias" }).click();
    const fila = page.getByRole("row").filter({ hasText: nombre });
    await expect(fila).toBeVisible();
    await expect(fila).toContainText("v1");

    // Limpieza: se elimina para no acumular plantillas activas (el bot de WhatsApp las ofrece).
    await fila.getByRole("button", { name: `Eliminar ${nombre}` }).click();
    await page.getByRole("dialog", { name: "Eliminar plantilla" }).getByRole("button", { name: "Sí, eliminar" }).click();
    await expect(page.getByRole("row").filter({ hasText: nombre })).toHaveCount(0);
    verificar();
  });
});
