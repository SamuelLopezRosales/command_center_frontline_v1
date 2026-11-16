import { altaColaborador, celularUnico, expect, iniciarSesion, SUFIJO, test, vigilarErroresApi } from "./base";

test.describe("2. Alta de colaborador", () => {
  test("se da de alta desde el formulario y aparece en el listado", async ({ page }) => {
    const verificar = vigilarErroresApi(page);
    const numero = `E2E-${SUFIJO}`;
    const apellido = `Prueba${SUFIJO}`;
    await iniciarSesion(page);

    await altaColaborador(page, { numero, nombres: "Elena", apellido, celular: celularUnico() });

    await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Colaboradores" }).click();
    await page.getByLabel("Buscar por nombre o número de empleado").fill(numero);
    const fila = page.getByRole("row").filter({ hasText: numero });
    await expect(fila, `el colaborador ${numero} debe aparecer en el listado`).toBeVisible();
    await expect(fila).toContainText(apellido);
    await expect(fila).toContainText("ACTIVO");

    await fila.getByRole("link", { name: /^Abrir/ }).click();
    await expect(page.getByLabel("Número de empleado")).toHaveValue(numero);
    verificar();
  });

  test("valida los datos obligatorios antes de enviar", async ({ page }) => {
    await iniciarSesion(page);
    await page.goto("/colaboradores/nuevo");
    await page.getByLabel("Celular con WhatsApp").fill("123");
    await page.getByRole("button", { name: "Guardar colaborador" }).click();
    await expect(page.getByText("El celular debe tener 10 dígitos.")).toBeVisible();
    await expect(page.getByText("Este campo es obligatorio.").first()).toBeVisible();
  });
});
