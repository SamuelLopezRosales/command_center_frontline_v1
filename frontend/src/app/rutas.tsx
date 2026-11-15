import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { RutasCampos } from "@/features/campos/RutasCampos";
import { RutasCarga } from "@/features/carga/RutasCarga";
import { RutasColaboradores } from "@/features/colaboradores/RutasColaboradores";
import { RutasConstancias } from "@/features/constancias/RutasConstancias";
import { Dashboard } from "@/features/dashboard/Dashboard";
import { RutasNotificaciones } from "@/features/notificaciones/RutasNotificaciones";
import { RutasOrganizaciones } from "@/features/organizaciones/RutasOrganizaciones";
import { RutasPublicas } from "@/features/publico/RutasPublicas";
import { PaginaAcceso } from "@/features/auth/PaginaAcceso";
import { PaginaRecuperar } from "@/features/auth/PaginaRecuperar";
import { PaginaRegistro } from "@/features/auth/PaginaRegistro";
import { es } from "@/shared/i18n/es";
import { useSesion } from "@/shared/sesion/SesionProvider";
import { Shell } from "./layout/Shell";

function Protegida({ children }: { children: ReactNode }) {
  const { estado } = useSesion();
  if (estado === "cargando") return <p role="status">{es.comun.cargando}</p>;
  if (estado === "anonima") return <Navigate to="/acceso" replace />;
  return <>{children}</>;
}

/**
 * Cada módulo es dueño de su subárbol de rutas (`<Routes>` anidado):
 * T-220: dashboard, colaboradores, campos, cargas, organizaciones.
 * T-221: constancias y las páginas públicas /v/:codigo y /d/:token (sin sesión).
 * T-222: notificaciones, chat y usuarios.
 */
export function Rutas() {
  return (
    <Routes>
      <Route path="/acceso" element={<PaginaAcceso />} />
      <Route path="/registro" element={<PaginaRegistro />} />
      <Route path="/recuperar" element={<PaginaRecuperar />} />
      <Route path="/v/:codigo" element={<RutasPublicas />} />
      <Route path="/d/:token" element={<RutasPublicas />} />
      <Route
        element={
          <Protegida>
            <Shell />
          </Protegida>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="colaboradores/*" element={<RutasColaboradores />} />
        <Route path="campos/*" element={<RutasCampos />} />
        <Route path="cargas/*" element={<RutasCarga />} />
        <Route path="organizaciones/*" element={<RutasOrganizaciones />} />
        <Route path="constancias/*" element={<RutasConstancias />} />
        <Route path="notificaciones/*" element={<RutasNotificaciones />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
