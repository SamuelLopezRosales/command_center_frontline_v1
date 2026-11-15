import { Navigate, Route, Routes } from "react-router-dom";
import { FormularioColaborador } from "./FormularioColaborador";
import { ListadoColaboradores } from "./ListadoColaboradores";

export function RutasColaboradores() {
  return (
    <Routes>
      <Route index element={<ListadoColaboradores />} />
      <Route path="nuevo" element={<FormularioColaborador />} />
      <Route path=":id" element={<FormularioColaborador />} />
      <Route path="*" element={<Navigate to="/colaboradores" replace />} />
    </Routes>
  );
}
