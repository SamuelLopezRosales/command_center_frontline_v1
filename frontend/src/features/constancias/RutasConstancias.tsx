import { Navigate, Route, Routes } from "react-router-dom";
import { EditorPlantilla } from "./editor/EditorPlantilla";
import { HistorialConstancias } from "./historial/HistorialConstancias";
import { ListadoPlantillas } from "./plantillas/ListadoPlantillas";

/** Montado en `constancias/*`: listado, historial y editor de plantilla. */
export function RutasConstancias() {
  return (
    <Routes>
      <Route index element={<ListadoPlantillas />} />
      <Route path="historial" element={<HistorialConstancias />} />
      <Route path=":id" element={<EditorPlantilla />} />
      <Route path="*" element={<Navigate to="/constancias" replace />} />
    </Routes>
  );
}
