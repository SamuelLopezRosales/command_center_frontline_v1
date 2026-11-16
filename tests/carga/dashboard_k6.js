// Carga del dashboard (DSH-01 a DSH-04) con 10,000 colaboradores y un año de constancias
// (T-142, design.md §15.3, CC-NFR-002). Candidato por confirmar (PQ-NFR): p95 menor a 1 s.
//
// Uso (k6 no está instalado; con Docker no hace falta instalarlo):
//   docker run --rm -i -e BASE_URL=https://<cloudfront o API> -e TOKEN=<access token de Cognito> \
//     grafana/k6 run - < tests/carga/dashboard_k6.js
// BASE_URL: servicio (local: http://host.docker.internal:8000) o CloudFront (AWS). Los datos se
// siembran antes (ver docs/resultados-carga-local.md); el guion no crea nada.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN;
if (!TOKEN) throw new Error("Falta TOKEN (access token de un usuario RH de la empresa de prueba)");

export const options = {
  scenarios: {
    dashboard: { executor: "constant-vus", vus: 10, duration: "2m", exec: "dashboard" },
  },
  thresholds: {
    "http_req_duration{endpoint:resumen}": ["p(95)<1000"],
    "http_req_duration{endpoint:solicitudes}": ["p(95)<1000"],
    "http_req_duration{endpoint:constancias}": ["p(95)<1000"],
    "http_req_duration{endpoint:alertas}": ["p(95)<1000"],
    http_req_failed: ["rate<0.01"],
  },
};

const cab = { Authorization: `Bearer ${TOKEN}` };

// La SPA pide las cuatro al abrir el dashboard.
export function dashboard() {
  const peticion = (ruta, endpoint) => ["GET", `${BASE_URL}${ruta}`, null, { headers: cab, tags: { endpoint } }];
  const respuestas = http.batch([
    peticion("/api/v1/dashboard/resumen", "resumen"),
    peticion("/api/v1/dashboard/solicitudes-recientes?limite=10", "solicitudes"),
    peticion("/api/v1/dashboard/constancias-recientes?limite=10", "constancias"),
    peticion("/api/v1/dashboard/alertas", "alertas"),
  ]);
  respuestas.forEach((r) => check(r, { "200": (x) => x.status === 200 }));
  sleep(1);
}
