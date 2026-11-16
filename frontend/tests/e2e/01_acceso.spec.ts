import { CONTRASENA_RH, CORREO_RH, expect, iniciarSesion, test } from "./base";

test.describe("1. Acceso con MFA simulado", () => {
  test("rechaza un código de 4 caracteres, acepta 000000 y permite cerrar sesión", async ({ page }) => {
    await page.goto("/acceso");
    await page.getByLabel("Usuario o correo").fill(CORREO_RH);
    await page.getByLabel("Contraseña").fill(CONTRASENA_RH);
    await page.getByRole("button", { name: "Iniciar sesión" }).click();

    await page.getByLabel("Código de verificación").fill("12ab");
    await page.getByRole("button", { name: "Verificar" }).click();
    await expect(page.getByText("El código tiene 6 dígitos."), "el código de 4 caracteres debió rechazarse").toBeVisible();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toHaveCount(0);

    await page.getByLabel("Código de verificación").fill("000000");
    await page.getByRole("button", { name: "Verificar" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByText("Ana", { exact: false }).first()).toBeVisible();

    await page.getByRole("button", { name: "Cerrar sesión" }).click();
    await expect(page.getByLabel("Usuario o correo"), "al cerrar sesión debe volver el formulario de acceso").toBeVisible();
    await page.goto("/colaboradores");
    await expect(page, "una ruta protegida sin sesión debe redirigir al acceso").toHaveURL(/\/acceso$/);
  });

  test("credenciales incorrectas muestran un mensaje genérico", async ({ page }) => {
    await page.goto("/acceso");
    await page.getByLabel("Usuario o correo").fill(CORREO_RH);
    await page.getByLabel("Contraseña").fill("Incorrecta-123!"); // pragma: allowlist secret
    await page.getByRole("button", { name: "Iniciar sesión" }).click();
    await expect(page.getByRole("alert")).toContainText("Correo o contraseña incorrectos.");
  });

  test("una sesión iniciada permite recorrer el menú principal", async ({ page }) => {
    await iniciarSesion(page);
    for (const [enlace, titulo] of [
      ["Colaboradores", "Colaboradores"],
      ["Constancias", "Constancias"],
      ["Notificaciones", "Notificaciones"],
      ["Chat", "Chat"],
      ["Usuarios", "Usuarios"],
    ] as const) {
      await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: enlace }).click();
      await expect(page.getByRole("heading", { name: titulo, exact: true }).first(), `no abrió «${enlace}»`).toBeVisible();
    }
  });
});
