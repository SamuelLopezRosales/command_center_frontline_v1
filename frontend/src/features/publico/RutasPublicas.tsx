import { Navigate, useParams } from "react-router-dom";
import { Descarga } from "./descarga/Descarga";
import { Verificacion } from "./verificacion/Verificacion";

/** Páginas públicas sin sesión: `/v/:codigo` (verificación) y `/d/:token` (descarga). */
export function RutasPublicas() {
  const { codigo, token } = useParams();
  if (codigo) return <Verificacion codigo={codigo} />;
  if (token) return <Descarga token={token} />;
  return <Navigate to="/" replace />;
}
