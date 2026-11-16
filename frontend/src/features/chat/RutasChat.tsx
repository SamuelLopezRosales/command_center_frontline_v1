import { Navigate, Route, Routes } from "react-router-dom";
import { PaginaChat } from "./PaginaChat";

/** Montado en `chat/*`: conversaciones, hilo, respuesta y asignación (T-222). */
export function RutasChat() {
  return (
    <Routes>
      <Route index element={<PaginaChat />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}
