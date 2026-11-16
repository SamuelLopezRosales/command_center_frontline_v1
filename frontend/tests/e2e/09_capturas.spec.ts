// Capturas de las pantallas principales para la revisión visual (T-134). No forma parte de la
// corrida normal: se activa con CC_E2E_CAPTURAS=1 (`npm run e2e:capturas`) y escribe en
// `docs/capturas_spa/` a 1440x900. Los datos son los de ejemplo del stack local (ficticios); los campos
// de celular se enmascaran.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { codigoDeVerificacion, RAIZ_REPO } from "./apoyo";
import { CONTRASENA_RH, CORREO_RH, expect, iniciarSesion, test } from "./base";

const DESTINO = join(RAIZ_REPO, "docs", "capturas_spa");

test.skip(!process.env.CC_E2E_CAPTURAS, "Las capturas solo se toman con CC_E2E_CAPTURAS=1 (npm run e2e:capturas).");
test.use({ viewport: { width: 1440, height: 900 } });

async function foto(page: Page, nombre: string, completa = false) {
  mkdirSync(DESTINO, { recursive: true });
  await page.waitForLoadState("networkidle");
  await page.screenshot({
    path: join(DESTINO, `${nombre}.png`),
    fullPage: completa,
    mask: [page.getByLabel(/celular/i)],
    maskColor: "#cccccc",
  });
}

test.describe("capturas de la SPA", () => {
  test("acceso y MFA (sin sesión)", async ({ page }) => {
    await page.goto("/acceso");
    await expect(page.getByLabel("Usuario o correo")).toBeVisible();
    await foto(page, "01_acceso");
    await page.getByLabel("Usuario o correo").fill(CORREO_RH);
    await page.getByLabel("Contraseña").fill(CONTRASENA_RH);
    await page.getByRole("button", { name: "Iniciar sesión" }).click();
    await expect(page.getByLabel("Código de verificación")).toBeVisible();
    await foto(page, "02_mfa");
  });

  test("pantallas con sesión", async ({ page }) => {
    test.setTimeout(240_000);
    await iniciarSesion(page);
    await expect(page.getByText("CG-").first()).toBeVisible();
    await foto(page, "03_dashboard", true);

    await page.goto("/colaboradores");
    await expect(page.getByRole("row").nth(1)).toBeVisible();
    await foto(page, "04_colaboradores_listado", true);

    await page.goto("/colaboradores/nuevo");
    await expect(page.getByLabel("Organización", { exact: true }).locator("option")).not.toHaveCount(1);
    await foto(page, "05_colaborador_formulario", true);

    await page.goto("/campos");
    await expect(page.getByRole("tab", { name: /Todos/ })).toBeVisible();
    await foto(page, "06_campos", true);

    await page.goto("/cargas");
    await expect(page.getByRole("button", { name: "Descargar plantilla" })).toBeVisible();
    await foto(page, "07_carga_masiva", true);

    await page.goto("/organizaciones");
    await expect(page.getByRole("heading", { name: /Organizaciones/ }).first()).toBeVisible();
    await foto(page, "08_organizaciones", true);

    await page.goto("/constancias");
    await expect(page.getByRole("table", { name: "Plantillas de constancia" })).toBeVisible();
    await foto(page, "09_plantillas");

    await page.getByRole("link", { name: /^Editar/ }).first().click();
    const documento = page.getByRole("textbox", { name: "Contenido de la constancia" });
    await expect(documento).toBeVisible();
    await expect(documento).toContainText("CONSTANCIA");
    await page.getByRole("button", { name: "Validar", exact: true }).click();
    await expect(page.getByText(/Sin errores|Aviso|Error/).first()).toBeVisible();
    await foto(page, "10_editor_plantilla", true);

    await page.goto("/constancias/historial");
    await expect(page.getByRole("table", { name: "Historial de constancias" })).toBeVisible();
    await foto(page, "11_historial", true);

    await page.goto("/notificaciones");
    await expect(page.getByRole("table", { name: "Notificaciones" })).toBeVisible();
    await foto(page, "13_notificaciones_listado", true);

    await page.goto("/notificaciones/plantillas");
    await expect(page.getByRole("table", { name: "Plantillas de mensaje" })).toBeVisible();
    await foto(page, "14_plantillas_mensaje");

    // Nueva notificación con embudo (no se envía: queda en la pantalla de revisión).
    await page.goto("/notificaciones/nueva");
    await page.getByLabel("Título del envío").fill("Aviso de cierre de nómina");
    await expect(page.getByLabel("Campo 1").locator("option")).not.toHaveCount(1);
    await page.getByLabel("Campo 1").selectOption("estatus");
    await page.getByLabel("Valor 1").selectOption("ACTIVO");
    const plantilla = page.getByLabel("Plantilla", { exact: true });
    await plantilla.selectOption({ label: (await plantilla.getByRole("option", { name: /aviso_general/ }).textContent())!.trim() });
    await page.getByLabel("Campo de {{1}}").selectOption("nombre_completo");
    await page.getByRole("button", { name: "Revisar y enviar" }).click();
    await expect(page.getByRole("list", { name: "Embudo de la audiencia" })).toBeVisible();
    await foto(page, "15_notificacion_nueva_embudo", true);

    // Detalle de un envío existente (los crean las corridas E2E) si lo hay.
    await page.goto("/notificaciones");
    const ver = page.getByRole("link", { name: /Ver detalle/ }).first();
    await ver.waitFor({ timeout: 5000 }).catch(() => undefined);
    if (await ver.count()) {
      await ver.click();
      await expect(page.getByRole("heading", { name: "Resultado del envío" })).toBeVisible();
      await foto(page, "16_detalle_envio", true);
    }

    await page.goto("/chat");
    await expect(page.getByRole("heading", { name: "Chat", exact: true })).toBeVisible();
    const conversacion = page.getByRole("button").filter({ hasText: /Ventana (abierta|cerrada)/ }).first();
    await conversacion.waitFor({ timeout: 5000 }).catch(() => undefined);
    if (await conversacion.count()) {
      await conversacion.click();
      await expect(page.getByText(/Elige una conversación/)).toHaveCount(0);
    }
    await foto(page, "17_chat", true);

    await page.goto("/usuarios");
    await expect(page.getByRole("table", { name: "Usuarios de la empresa" })).toBeVisible();
    await foto(page, "18_usuarios");
    await page.getByRole("button", { name: "Invitar usuario" }).click();
    await foto(page, "19_usuarios_invitar");
    await page.getByRole("button", { name: "Cancelar" }).click();

    await page.goto("/usuarios/bitacora");
    await expect(page.getByRole("table", { name: "Registros de la bitácora" })).toBeVisible();
    await foto(page, "20_bitacora", true);
  });

  test("verificación pública de una constancia real (sin sesión)", async ({ page }) => {
    const codigo = codigoDeVerificacion();
    test.skip(!codigo, "No hay constancias generadas: no hay código real que verificar.");
    await page.goto(`/v/${codigo}`);
    await expect(page.getByRole("heading").first()).toBeVisible();
    await foto(page, "12_verificacion_publica");
  });
});
