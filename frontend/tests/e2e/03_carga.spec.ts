import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { python } from "./apoyo";
import { expect, iniciarSesion, SUFIJO, test, vigilarErroresApi } from "./base";

test.describe("3. Carga masiva", () => {
  test("descarga la plantilla, sube un Excel válido y sigue la carga hasta TERMINADA", async ({ page }) => {
    const verificar = vigilarErroresApi(page);
    const carpeta = mkdtempSync(join(tmpdir(), "cc-e2e-"));
    await iniciarSesion(page);
    await page.goto("/cargas");
    await expect(page.getByRole("heading", { name: "Carga masiva de colaboradores" })).toBeVisible();

    // 1. Descarga de la plantilla (con el token en el encabezado, no en la URL).
    const [descarga] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Descargar plantilla" }).click()]);
    const plantilla = join(carpeta, "plantilla.xlsx");
    await descarga.saveAs(plantilla);
    expect(readFileSync(plantilla).subarray(0, 2).toString(), "la plantilla debe ser un .xlsx (zip)").toBe("PK");

    // 2. Se llenan dos filas y se sube.
    const lleno = join(carpeta, `empleados_${SUFIJO}.xlsx`);
    const { numeros } = python<{ numeros: string[] }>("preparar_carga.py", [plantilla, lleno, SUFIJO, "2", "0"]);
    await page.getByLabel("Archivo de carga").setInputFiles(lleno);
    await page.getByRole("button", { name: "Subir y validar" }).click();

    // 3. Seguimiento hasta TERMINADA.
    await expect(page, "tras subir debe abrirse el seguimiento de la carga").toHaveURL(/\/cargas\/\d+$/, { timeout: 30_000 });
    await expect(page.getByText("Terminada", { exact: true }), "la carga debió terminar (revise worker-cargas: .\scripts\local.ps1 logs worker-cargas)").toBeVisible({ timeout: 60_000 });
    const resumen = page.getByRole("region", { name: "Resumen" });
    await expect(resumen).toContainText("Filas correctas");
    await expect(resumen.getByText("2", { exact: true }).first()).toBeVisible();

    // 4. Los colaboradores quedan en el listado.
    await page.goto("/colaboradores");
    await page.getByLabel("Buscar por nombre o número de empleado").fill(numeros[0]!);
    await expect(page.getByRole("row").filter({ hasText: numeros[0]! })).toBeVisible();
    verificar();
  });

  test("una fila con error se informa y ofrece el reporte de errores", async ({ page }) => {
    const carpeta = mkdtempSync(join(tmpdir(), "cc-e2e-"));
    await iniciarSesion(page);
    await page.goto("/cargas");
    const [descarga] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Descargar plantilla" }).click()]);
    const plantilla = join(carpeta, "plantilla.xlsx");
    await descarga.saveAs(plantilla);
    const sufijo = `${SUFIJO}X`;
    const lleno = join(carpeta, `con_error_${sufijo}.xlsx`);
    python("preparar_carga.py", [plantilla, lleno, sufijo, "2", "1"]);
    await page.getByLabel("Archivo de carga").setInputFiles(lleno);
    await page.getByRole("button", { name: "Subir y validar" }).click();
    await expect(page).toHaveURL(/\/cargas\/\d+$/, { timeout: 30_000 });
    await expect(page.getByText("Terminada", { exact: true })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("El celular debe tener 10 dígitos.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Descargar reporte de errores" })).toBeVisible();
  });
});
