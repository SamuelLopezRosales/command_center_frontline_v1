// Despacho de una notificación a 10,000 destinatarios (T-142, design.md §15.4, CC-NFR-003).
//
// El despacho no es una ráfaga HTTP: lo hace la Lambda `despachador` por bloques de 500 y lotes de
// 10 hacia `wa-salida.fifo`. Este guion lanza UNA confirmación y mide cuánto tarda la notificación
// en salir de ENVIANDO (más el tiempo de la propia confirmación). En AWS el envío real depende del
// nivel de mensajería de Meta (PQ-27): en `test` usa la cuenta y plantilla de prueba o el simulador,
// nunca números reales de colaboradores.
//
// Preparación (fuera del guion): una notificación en BORRADOR ya revisada (POST .../revisar) sobre
// una audiencia de 10,000 colaboradores con consentimiento.
//   docker run --rm -i -e BASE_URL=... -e TOKEN=... -e NOTIFICACION_ID=<id> \
//     grafana/k6 run - < tests/carga/despacho_k6.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN;
const ID = __ENV.NOTIFICACION_ID;
if (!TOKEN || !ID) throw new Error("Faltan TOKEN y NOTIFICACION_ID");

const despachoTotal = new Trend("despacho_total_s");

export const options = {
  scenarios: {
    despacho: { executor: "shared-iterations", vus: 1, iterations: 1, maxDuration: "30m" },
  },
  thresholds: {
    // Candidato por confirmar: 10,000 destinatarios despachados en menos de 10 minutos.
    despacho_total_s: ["max<600"],
    http_req_failed: ["rate<0.01"],
  },
};

const cab = { headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" } };

export default function () {
  const t0 = Date.now();
  const c = http.post(
    `${BASE_URL}/api/v1/notificaciones/${ID}/confirmar`,
    JSON.stringify({ modo_envio: "AHORA", confirmar_fuera_horario: true }),
    cab,
  );
  check(c, { "confirmar 2xx": (r) => r.status >= 200 && r.status < 300 });
  for (let i = 0; i < 1800; i++) {
    const d = http.get(`${BASE_URL}/api/v1/notificaciones/${ID}`, cab);
    const estado = d.status === 200 ? d.json("estado") : null;
    if (["COMPLETADA", "CON_FALLAS", "CANCELADA"].includes(estado)) break;
    sleep(1);
  }
  despachoTotal.add((Date.now() - t0) / 1000);
}
