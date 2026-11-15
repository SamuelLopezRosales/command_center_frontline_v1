import { Navigate, Route, Routes } from "react-router-dom";
import { DetalleCarga } from "./DetalleCarga";
import { PaginaCarga } from "./PaginaCarga";

export function RutasCarga() {
  return (
    <Routes>
      <Route index element={<PaginaCarga />} />
      <Route path=":id" element={<DetalleCarga />} />
      <Route path="*" element={<Navigate to="/cargas" replace />} />
    </Routes>
  );
}
