import { Navigate, Route, Routes } from "react-router-dom";
import { DetalleEnvio } from "./detalle/DetalleEnvio";
import { ListadoNotificaciones } from "./listado/ListadoNotificaciones";
import { NuevaNotificacion } from "./nueva/NuevaNotificacion";
import { PlantillasMensaje } from "./plantillas_mensaje/PlantillasMensaje";

/** Montado en `notificaciones/*`: listado, plantillas de mensaje, nueva, edición de borrador y detalle. */
export function RutasNotificaciones() {
  return (
    <Routes>
      <Route index element={<ListadoNotificaciones />} />
      <Route path="plantillas" element={<PlantillasMensaje />} />
      <Route path="nueva" element={<NuevaNotificacion />} />
      <Route path=":id/editar" element={<NuevaNotificacion />} />
      <Route path=":id" element={<DetalleEnvio />} />
      <Route path="*" element={<Navigate to="/notificaciones" replace />} />
    </Routes>
  );
}
