import { expect, iniciarSesion, SUFIJO, test, vigilarErroresApi } from "./base";

test.describe("8. Usuarios e invitaciones", () => {
  test("crea una invitación: el código se muestra una vez y desaparece al cerrar", async ({ page }) => {
    const verificar = vigilarErroresApi(page);
    await iniciarSesion(page);
    await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Usuarios" }).click();
    const tabla = page.getByRole("table", { name: "Usuarios de la empresa" });
    await expect(tabla).toContainText("ana.rh@demo.test");

    await page.getByRole("button", { name: "Invitar usuario" }).click();
    await page.getByLabel("Correo de la persona invitada (opcional)").fill(`invitada.${SUFIJO.toLowerCase()}@demo.test`);
    await page.getByRole("button", { name: "Crear invitación" }).click();

    const dialogo = page.getByRole("dialog", { name: "Invitación creada" });
    await expect(dialogo).toBeVisible();
    const codigo = (await dialogo.locator("code.usr-codigo").textContent())?.trim();
    expect(codigo, "el código de invitación debe mostrarse en el cuadro").toMatch(/^[A-Za-z0-9_-]{16,}$/);
    await expect(dialogo).toContainText("no se podrá volver a ver");

    await dialogo.getByRole("button", { name: "Cerrar" }).click();
    await expect(dialogo).toHaveCount(0);
    // El código no queda en la pantalla ni en el almacenamiento del navegador.
    await expect(page.getByText(codigo!)).toHaveCount(0);
    const guardado = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    expect(guardado).not.toContain(codigo!);
    // Al recargar tampoco se puede recuperar.
    await page.reload();
    await expect(page.getByText(codigo!)).toHaveCount(0);
    verificar();
  });

  test("el usuario en sesión no puede desactivarse y la bitácora registra acciones", async ({ page }) => {
    await iniciarSesion(page);
    await page.goto("/usuarios");
    const fila = page.getByRole("row").filter({ hasText: "ana.rh@demo.test" });
    await expect(fila).toContainText("(tú)");
    await expect(fila.getByRole("button", { name: /Desactivar/ })).toHaveCount(0);

    await page.getByRole("link", { name: "Ver bitácora" }).click();
    await expect(page.getByRole("heading", { name: "Bitácora" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Registros de la bitácora" })).toBeVisible();
    await expect(page.getByRole("row")).not.toHaveCount(1);
  });
});
