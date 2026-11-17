import { expect, iniciarSesion, test, vigilarErroresApi } from "./base";

// Datos de ejemplo inventados: NUNCA se usan credenciales reales en estas pruebas.
const WABA = "100200300400500";
const NUMERO = "600700800900100";
const TOKEN = "EAAdatos-de-ejemplo-no-reales-0123456789ABCD"; // pragma: allowlist secret
const APP_SECRET = "00112233445566778899aabbccddeeff"; // pragma: allowlist secret

test.describe("10. Conexión con Meta", () => {
  test("captura datos de ejemplo, genera el token de verificación una sola vez y prueba la conexión", async ({ page }) => {
    const verificar = vigilarErroresApi(page);
    await iniciarSesion(page);
    await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Meta" }).click();
    await expect(page.getByRole("heading", { name: "Conexión con Meta", level: 1 })).toBeVisible();
    await expect(page.getByText("Pantalla pendiente de validación visual con Samuel.")).toBeVisible();

    // La URL del webhook sale del mismo dominio que sirve la SPA.
    await expect(page.getByRole("region", { name: "URL del webhook" })).toContainText(`${new URL(page.url()).origin}/webhook/meta`);

    // Guardar solo lo escrito: los secretos son campos de contraseña.
    await page.getByLabel("WABA ID").fill(WABA);
    await page.getByLabel("Phone Number ID").fill(NUMERO);
    const campoToken = page.getByLabel("Token de acceso permanente");
    await expect(campoToken).toHaveAttribute("type", "password");
    await campoToken.fill(TOKEN);
    await page.getByLabel("App Secret").fill(APP_SECRET);
    await page.getByRole("button", { name: "Guardar cambios" }).click();
    await expect(page.getByText(/Cambios guardados/)).toBeVisible();
    // Tras guardar el secreto sale de la pantalla y queda enmascarado.
    await expect(page.getByText("Configurado · termina en ••••ABCD")).toBeVisible();
    await expect(page.locator("input[type=password]")).toHaveCount(0);

    // Verify token: se muestra una vez y no reaparece.
    await page.getByRole("button", { name: "Generar", exact: true }).click();
    await page.getByRole("button", { name: "Generar token" }).click();
    const dialogo = page.getByRole("dialog", { name: "Token de verificación generado" });
    const verify = (await dialogo.locator("code").textContent())?.trim();
    expect(verify).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    await expect(dialogo).toContainText("no se podrá volver a ver");
    await dialogo.getByRole("button", { name: "Cerrar" }).click();
    await expect(page.getByText(verify!)).toHaveCount(0);
    const guardado = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    for (const secreto of [TOKEN, APP_SECRET, verify!]) expect(guardado).not.toContain(secreto);
    await page.reload();
    await expect(page.getByText(verify!)).toHaveCount(0);

    // En local «Probar» llama a graph.facebook.com de verdad: con datos de ejemplo el token no es válido.
    await page.getByRole("button", { name: "Probar conexión" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: "Token de acceso: Falló" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Hay datos por corregir")).toBeVisible();
    verificar();
  });
});
