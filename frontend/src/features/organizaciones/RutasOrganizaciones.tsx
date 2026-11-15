import { Link, NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { Organizaciones } from "./Organizaciones";
import "./organizaciones.css";
import { Plantas } from "./Plantas";
import { textos as t } from "./textos";

function Marco() {
  return (
    <>
      <div className="encabezado">
        <div>
          <h1>{t.titulo}</h1>
          <p>{t.subtitulo}</p>
        </div>
        <Link className="btn btn-contorno" to="/colaboradores">
          {t.volver}
        </Link>
      </div>
      <nav className="org-pestanas" aria-label="Catálogos">
        <NavLink to="/organizaciones" end className={({ isActive }) => (isActive ? "activo" : undefined)}>
          {t.pestanas.organizaciones}
        </NavLink>
        <NavLink to="/organizaciones/plantas" className={({ isActive }) => (isActive ? "activo" : undefined)}>
          {t.pestanas.plantas}
        </NavLink>
      </nav>
      <Outlet />
    </>
  );
}

export function RutasOrganizaciones() {
  return (
    <Routes>
      <Route element={<Marco />}>
        <Route index element={<Organizaciones />} />
        <Route path="plantas" element={<Plantas />} />
      </Route>
      <Route path="*" element={<Navigate to="/organizaciones" replace />} />
    </Routes>
  );
}
