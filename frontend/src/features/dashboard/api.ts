import { solicitar } from "@/api-client/http";
import type { Alerta, ItemConstancia, ItemSolicitud, ResumenDashboard } from "./tipos";

export const apiDashboard = {
  resumen: () => solicitar<ResumenDashboard>("/api/v1/dashboard/resumen"),
  solicitudes: (limite = 5) => solicitar<ItemSolicitud[]>("/api/v1/dashboard/solicitudes-recientes", { consulta: { limite } }),
  constancias: (limite = 5) => solicitar<ItemConstancia[]>("/api/v1/dashboard/constancias-recientes", { consulta: { limite } }),
  alertas: () => solicitar<Alerta[]>("/api/v1/dashboard/alertas"),
};
