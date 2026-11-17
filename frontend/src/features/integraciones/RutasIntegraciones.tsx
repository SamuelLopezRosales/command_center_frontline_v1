import { Navigate, Route, Routes } from "react-router-dom";
import { PaginaMeta } from "./PaginaMeta";

/** Montado en `integraciones/*`: por ahora solo la conexión con Meta. */
export function RutasIntegraciones() {
  return (
    <Routes>
      <Route path="meta" element={<PaginaMeta />} />
      <Route path="*" element={<Navigate to="/integraciones/meta" replace />} />
    </Routes>
  );
}
