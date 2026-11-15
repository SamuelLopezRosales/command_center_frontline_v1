// Prueba de carga de listado y búsqueda de colaboradores (T-204, design.md §15.3, CC-NFR-002).
//
// Mide con 10,000 colaboradores en la empresa de prueba. Valor candidato por confirmar (PQ-NFR):
// p95 menor a 1 s en listados y búsquedas.
//
// Uso (k6 no se instala por defecto; con Docker no hace falta instalarlo):
//   docker run --rm -i -e BASE_URL=http://host.docker.internal:8000 -e TOKEN=<access token> \
//     grafana/k6 run - < tests/carga/colaboradores_k6.js
//
// BASE_URL apunta al servicio (local) o a CloudFront (AWS). TOKEN es un access token de Cognito
// de un usuario de la empresa de prueba. En local se puede emitir uno con las llaves de prueba.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN;

export const options = {
  scenarios: {
    listados: {
      executor: "constant-vus",
      vus: 10,
      duration: "1m",
      exec: "listado",
    },
    busquedas: {
      executor: "constant-vus",
      vus: 10,
      duration: "1m",
      exec: "busqueda",
    },
  },
  thresholds: {
    "http_req_duration{scenario:listados}": ["p(95)<1000"],
    "http_req_duration{scenario:busquedas}": ["p(95)<1000"],
    http_req_failed: ["rate<0.01"],
  },
};

const cabeceras = { headers: { Authorization: `Bearer ${TOKEN}` } };
const NOMBRES = ["maria", "jose", "ana", "luis", "carmen", "jorge"];

export function listado() {
  const pagina = 1 + Math.floor(Math.random() * 100);
  const r = http.get(`${BASE_URL}/api/v1/colaboradores?pagina=${pagina}&limite=50`, cabeceras);
  check(r, { "listado 200": (x) => x.status === 200 });
  sleep(0.2);
}

export function busqueda() {
  const nombre = NOMBRES[Math.floor(Math.random() * NOMBRES.length)];
  const numero = String(Math.floor(Math.random() * 10000)).padStart(6, "0");
  const q = Math.random() < 0.5 ? nombre : `N-${numero}`;
  const r = http.get(`${BASE_URL}/api/v1/colaboradores?q=${encodeURIComponent(q)}`, cabeceras);
  check(r, { "busqueda 200": (x) => x.status === 200 });
  sleep(0.2);
}
