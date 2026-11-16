// Carga del historial de constancias (DSH-11) con unas 6,000 constancias (T-142, design.md §15.3).
// Candidato por confirmar: p95 menor a 1 s. La paginación es por cursor (campo "siguiente").
//
// Uso:
//   docker run --rm -i -e BASE_URL=https://<cloudfront o API> -e TOKEN=<access token> \
//     -e PLANTILLA_ID=<id de una plantilla de la empresa> grafana/k6 run - < tests/carga/historial_k6.js
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN;
const PLANTILLA_ID = __ENV.PLANTILLA_ID || "1";
if (!TOKEN) throw new Error("Falta TOKEN (access token de un usuario RH de la empresa de prueba)");

export const options = {
  scenarios: {
    filtros: { executor: "constant-vus", vus: 10, duration: "2m", exec: "filtros" },
    recorrido: { executor: "constant-vus", vus: 3, duration: "2m", exec: "recorrido" },
  },
  thresholds: {
    "http_req_duration{scenario:filtros}": ["p(95)<1000"],
    "http_req_duration{scenario:recorrido}": ["p(95)<1000"],
    http_req_failed: ["rate<0.01"],
  },
};

const cabeceras = { headers: { Authorization: `Bearer ${TOKEN}` } };
const H = `${BASE_URL}/api/v1/constancias/historial`;
const NOMBRES = ["maria", "jose", "ana", "luis", "ramirez", "lopez"];

export function filtros() {
  const nombre = NOMBRES[Math.floor(Math.random() * NOMBRES.length)];
  const folio = "CG-2026-00" + String(10 + Math.floor(Math.random() * 80));
  const rutas = [
    `${H}?limite=20`,
    `${H}?estado=FALLIDA&limite=50`,
    `${H}?plantilla_id=${PLANTILLA_ID}&limite=50`,
    `${H}?desde=2026-01-01&hasta=2026-12-31&limite=50`,
    `${H}?q=${encodeURIComponent(nombre)}`,
    `${H}?q=${encodeURIComponent(folio)}`,
  ];
  const r = http.get(rutas[Math.floor(Math.random() * rutas.length)], cabeceras);
  check(r, { "historial 200": (x) => x.status === 200 });
  sleep(0.2);
}

// Pagina hacia abajo siguiendo el cursor, como el desplazamiento infinito de la SPA.
export function recorrido() {
  let cursor = null;
  for (let i = 0; i < 25; i++) {
    const url = `${H}?limite=20${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`;
    const r = http.get(url, cabeceras);
    check(r, { "pagina 200": (x) => x.status === 200 });
    cursor = r.status === 200 ? r.json("siguiente") : null;
    if (!cursor) break;
    sleep(0.1);
  }
}
