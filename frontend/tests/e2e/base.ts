// Base común de las pruebas E2E: salta si el stack no responde y expone ayudas de uso frecuente.
import { expect, test as base, type Page } from "@playwright/test";

export const CORREO_RH = "ana.rh@demo.test";
export const CONTRASENA_RH = "Desarrollo-Local-1!"; // pragma: allowlist secret

/** Sufijo único por corrida (milisegundos en base 36) para repetir pruebas sin limpiar datos. */
export const SUFIJO = Date.now().toString(36).toUpperCase();

export const test = base.extend<{ stack: void }>({
  stack: [
    async ({}, use, testInfo) => {
      testInfo.skip(Boolean(process.env.CC_E2E_SIN_STACK), `El stack local no responde: ${process.env.CC_E2E_SIN_STACK}. Levántalo con .\scripts\local.ps1 up`);
      await use();
    },
    { auto: true },
  ],
});

export { expect };

/** Entra con correo, contraseña y un código MFA de 6 dígitos (el stack local acepta cualquiera). */
export async function iniciarSesion(page: Page, correo = CORREO_RH, contrasena = CONTRASENA_RH) {
  await page.goto("/acceso");
  await page.getByLabel("Usuario o correo").fill(correo);
  await page.getByLabel("Contraseña").fill(contrasena);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await page.getByLabel("Código de verificación").fill("000000");
  await page.getByRole("button", { name: "Verificar" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" }), "no se llegó al dashboard después del MFA").toBeVisible();
}

/** Respuestas de la API que deben ser correctas: un 4xx/5xx inesperado falla con la URL. */
export function vigilarErroresApi(page: Page, ignorar: RegExp[] = []) {
  const errores: string[] = [];
  page.on("response", (r) => {
    const url = r.url();
    if (r.status() >= 500 && url.includes("/api/") && !ignorar.some((x) => x.test(url))) errores.push(`${r.status()} ${r.request().method()} ${url}`);
  });
  return () => expect(errores, "la API respondió con errores 5xx").toEqual([]);
}

/** Celular ficticio de 10 dígitos, distinto en cada llamada (prefijo 55 + 8 dígitos del tiempo). */
let contadorCelular = 0;
export function celularUnico(): string {
  const base = (Date.now() % 100_000_000) + contadorCelular++;
  return `55${String(base % 100_000_000).padStart(8, "0")}`;
}

export interface DatosColaborador {
  numero: string;
  nombres: string;
  apellido: string;
  celular: string;
  /** Fecha de ingreso `aaaa-mm-dd`; su día y mes son el dato de verificación del bot. */
  ingreso?: string;
}

/** Da de alta un colaborador con consentimiento desde el formulario de la SPA y espera a que se guarde. */
export async function altaColaborador(page: Page, d: DatosColaborador) {
  await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Colaboradores" }).click();
  await page.getByRole("link", { name: "+ Nuevo colaborador" }).click();
  await expect(page.getByRole("heading", { name: "Nuevo colaborador" })).toBeVisible();

  await page.getByLabel("Número de empleado").fill(d.numero);
  await page.getByLabel("Nombre(s)").fill(d.nombres);
  await page.getByLabel("Apellido paterno").fill(d.apellido);
  await page.getByLabel("Apellido materno").fill("Ficticia");
  await page.getByLabel("Celular con WhatsApp").fill(d.celular);
  // Las listas se llenan con la respuesta de la API: se espera a que tengan opciones reales.
  const organizacion = page.getByLabel("Organización", { exact: true });
  await expect(organizacion.locator("option")).not.toHaveCount(1);
  await organizacion.selectOption({ index: 1 });
  const planta = page.getByLabel("Planta o centro de trabajo");
  await expect(planta.locator("option")).not.toHaveCount(1);
  await planta.selectOption({ index: 1 });
  await page.getByLabel("Fecha de ingreso").fill(d.ingreso ?? "2025-02-03");
  await page.getByLabel("Puesto").fill("Analista de pruebas");
  await page.getByLabel("Tipo de empleado").selectOption("ADMINISTRATIVO");
  await page.getByRole("checkbox", { name: /consentimiento/ }).check();

  // Campos adicionales obligatorios que haya configurados en este stack.
  for (const campo of await page.locator("[aria-required='true']:not([disabled])").all()) {
    const tipo = await campo.evaluate((e) => (e as HTMLInputElement | HTMLSelectElement).tagName + ":" + ((e as HTMLInputElement).type ?? ""));
    if ((await campo.inputValue()) !== "") continue;
    if (tipo.startsWith("SELECT")) await campo.selectOption({ index: 1 });
    else if (tipo.endsWith("number")) await campo.fill("1");
    else if (tipo.endsWith("date")) await campo.fill("2025-01-01");
    else await campo.fill("Dato ficticio");
  }

  await page.getByRole("button", { name: "Guardar colaborador" }).click();
  await expect(page.getByRole("heading", { name: "Nuevo colaborador" }), "el formulario debió cerrarse al guardar (revise errores de validación)").toHaveCount(0);
}
