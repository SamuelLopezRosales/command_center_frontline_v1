import { Navigate, Route, Routes } from "react-router-dom";
import { Bitacora } from "./Bitacora";
import { ListadoUsuarios } from "./ListadoUsuarios";

/** Montado en `usuarios/*`: listado con invitaciones y bitácora (T-222). */
export function RutasUsuarios() {
  return (
    <Routes>
      <Route index element={<ListadoUsuarios />} />
      <Route path="bitacora" element={<Bitacora />} />
      <Route path="*" element={<Navigate to="/usuarios" replace />} />
    </Routes>
  );
}
