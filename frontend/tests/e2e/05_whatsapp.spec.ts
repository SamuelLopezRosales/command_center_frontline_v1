// Constancia por WhatsApp simulado (T-133). En el stack local no hay webhook ni Lambdas: la prueba
// escribe en `wa-entrada.fifo` lo que haría `webhook-meta` y lee lo que el bot responde del outbox
// de `whatsapp`. NO se prueba la entrega por Meta (no hay enviador): la solicitud, la constancia
// generada por el worker de PDF y su aparición en la SPA sí.
import { escribirComoColaborador, respuestasDelBot } from "./apoyo";
import { altaColaborador, celularUnico, expect, iniciarSesion, SUFIJO, test, vigilarErroresApi } from "./base";

test.describe("5. Constancia por WhatsApp simulado", () => {
  test("el colaborador pide su constancia, se verifica y la constancia aparece en el historial", async ({ page }) => {
    test.setTimeout(180_000);
    const verificar = vigilarErroresApi(page);
    const celular = celularUnico();
    const waId = `52${celular}`;
    const apellido = `Whatsapp${SUFIJO}`;
    await iniciarSesion(page);
    // Ingreso 3 de febrero: el bot pide el día y mes de ingreso (sin NSS configurado).
    await altaColaborador(page, { numero: `WA-${SUFIJO}`, nombres: "Marcela", apellido, celular, ingreso: "2025-02-03" });

    // 1. Palabra clave: el bot manda el aviso de privacidad y el código con su desafío.
    escribirComoColaborador(waId, { texto: "Constancia" });
    const codigoMsg = respuestasDelBot(waId, { contiene: "Tu código de verificación es", esperaSeg: 40 });
    expect(codigoMsg.agotado, "el bot no respondió con el código (¿corre worker-whatsapp? .\scripts\local.ps1 logs worker-whatsapp)").toBeUndefined();
    const texto = codigoMsg.mensajes.map((m) => m.texto ?? "").join("\n");
    const codigo = /código de verificación es (\d{6})/.exec(texto)?.[1];
    expect(codigo, `no se encontró el código en: ${texto}`).toBeTruthy();
    expect(texto).toContain("fecha de ingreso");
    const ultimo = Math.max(...codigoMsg.mensajes.map((m) => m.id));

    // Un dato incorrecto no verifica.
    escribirComoColaborador(waId, { texto: `${codigo} 01/01` });
    const mal = respuestasDelBot(waId, { desde: ultimo, contiene: "no coinciden", esperaSeg: 40 });
    expect(mal.agotado, "el bot debió rechazar el dato incorrecto").toBeUndefined();
    const ultimo2 = Math.max(...mal.mensajes.map((m) => m.id));

    // 2. Respuesta correcta: verificado y, con una sola plantilla, la constancia queda en camino.
    escribirComoColaborador(waId, { texto: `${codigo} 03/02` });
    let r = respuestasDelBot(waId, { desde: ultimo2, esperaSeg: 40 });
    const menu = r.mensajes.find((m) => m.interactivo);
    if (menu) {
      const fila = menu.interactivo!.action!.sections![0]!.rows.find((f) => f.title.startsWith("Constancia laboral"));
      expect(fila, "el menú debe ofrecer «Constancia laboral»").toBeTruthy();
      escribirComoColaborador(waId, { interactivo: fila!.id });
      r = respuestasDelBot(waId, { desde: menu.id, contiene: "constancia", esperaSeg: 40 });
    }
    const ultimaRespuesta = r.mensajes.map((m) => m.texto ?? "").join("\n");
    expect(ultimaRespuesta, "el bot debió confirmar que prepara la constancia").toMatch(/constancia|preparando|camino/i);

    // 3. En la SPA: la constancia generada por el worker de PDF aparece en el historial.
    // El enlace `?q=` aplica el filtro; cada intento recarga la pantalla para consultar de nuevo.
    await expect(async () => {
      await page.goto(`/constancias/historial?q=${apellido}`);
      await expect(page.getByRole("row").filter({ hasText: apellido }), "la constancia no aparece en el historial (¿corre el worker de PDF en Docker?)").toBeVisible({ timeout: 4000 });
    }).toPass({ timeout: 90_000, intervals: [3000] });
    const fila = page.getByRole("row").filter({ hasText: apellido });
    await expect(fila).toContainText("WhatsApp");
    // Sin enviador ni Meta la entrega no avanza: queda Pendiente (límite documentado del stack local).
    await expect(fila).toContainText(/Pendiente|Entregada/);

    // 4. El dashboard refleja la solicitud/constancia reciente.
    await page.getByRole("navigation", { name: "Principal" }).getByRole("link", { name: "Dashboard" }).click();
    await expect(page.getByText(`Marcela ${apellido}`).first()).toBeVisible();
    verificar();
  });

  test("un número que no es de ningún colaborador recibe la respuesta de sin acceso", async () => {
    const waId = `52${celularUnico()}`;
    escribirComoColaborador(waId, { texto: "constancia" });
    const r = respuestasDelBot(waId, { esperaSeg: 40 });
    expect(r.agotado, "el bot debió contestar al número desconocido").toBeUndefined();
    expect(r.mensajes[0]!.texto).toBeTruthy();
    expect(r.mensajes[0]!.texto).not.toMatch(/\d{6}/); // jamás se emite un código
  });
});
