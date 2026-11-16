// Respuesta del webhook de Meta (T-142, design.md §4.2 y §15.3). Candidato por confirmar: p95
// menor a 1 s. Incluye el arranque en frío de la Lambda si el volumen sube de golpe.
//
// Firma cada cuerpo con X-Hub-Signature-256 (HMAC-SHA256 con el secreto de la aplicación de
// PRUEBA; nunca uses el de producción). Las peticiones sin firma o con firma inválida esperan 403.
//   docker run --rm -i -e BASE_URL=https://<cloudfront> -e APP_SECRET=<secreto de la app de prueba> \
//     -e PHONE_NUMBER_ID=<id del número de prueba> grafana/k6 run - < tests/carga/webhook_k6.js
import http from "k6/http";
import { check } from "k6";
import crypto from "k6/crypto";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const APP_SECRET = __ENV.APP_SECRET;
const PHONE_NUMBER_ID = __ENV.PHONE_NUMBER_ID || "PN-PRUEBA";
if (!APP_SECRET) throw new Error("Falta APP_SECRET (secreto de la aplicación de Meta de prueba)");

export const options = {
  scenarios: {
    rafaga: {
      executor: "ramping-arrival-rate",
      startRate: 1,
      timeUnit: "1s",
      preAllocatedVUs: 30,
      maxVUs: 100,
      stages: [
        { target: 10, duration: "30s" },
        { target: 50, duration: "1m" },
        { target: 10, duration: "30s" },
      ],
    },
  },
  thresholds: {
    "http_req_duration{tipo:firmado}": ["p(95)<1000"],
    "checks{tipo:rechazo}": ["rate==1"],
    // Los 403 esperados cuentan como fallo de k6; son una de cada 20 iteraciones.
    http_req_failed: ["rate<0.15"],
  },
};

function cuerpo(i) {
  return JSON.stringify({
    object: "whatsapp_business_account",
    entry: [
      {
        id: "WABA-PRUEBA",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: "0000000000", phone_number_id: PHONE_NUMBER_ID },
              contacts: [{ profile: { name: "Prueba" }, wa_id: "5210000000000" }],
              messages: [
                {
                  from: "5210000000000",
                  id: `wamid.K6${Date.now()}${i}${Math.floor(Math.random() * 1e6)}`,
                  timestamp: "1",
                  type: "text",
                  text: { body: "hola" },
                },
              ],
            },
          },
        ],
      },
    ],
  });
}

export default function () {
  const c = cuerpo(__ITER);
  const firma = "sha256=" + crypto.hmac("sha256", APP_SECRET, c, "hex");
  const url = `${BASE_URL}/webhook/meta`;
  const h = { "Content-Type": "application/json" };
  const ok = http.post(url, c, { headers: { ...h, "X-Hub-Signature-256": firma }, tags: { tipo: "firmado" } });
  check(ok, { "firmado 200": (r) => r.status === 200 }, { tipo: "firmado" });
  if (__ITER % 20 === 0) {
    const sinFirma = http.post(url, c, { headers: h, tags: { tipo: "rechazo" } });
    const mala = http.post(url, c, {
      headers: { ...h, "X-Hub-Signature-256": "sha256=" + "0".repeat(64) },
      tags: { tipo: "rechazo" },
    });
    check(sinFirma, { "sin firma 403": (r) => r.status === 403 }, { tipo: "rechazo" });
    check(mala, { "firma invalida 403": (r) => r.status === 403 }, { tipo: "rechazo" });
  }
}
