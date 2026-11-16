import { NavLink, Outlet } from "react-router-dom";
import logoHonne from "@/assets/imagen-honne.png";
import { es } from "@/shared/i18n/es";
import { useSesion } from "@/shared/sesion/SesionProvider";

const ENLACES = [
  { a: "/", texto: es.nav.dashboard, fin: true },
  { a: "/colaboradores", texto: es.nav.colaboradores },
  { a: "/constancias", texto: es.nav.constancias },
  { a: "/notificaciones", texto: es.nav.notificaciones },
  { a: "/chat", texto: es.nav.chat },
  { a: "/usuarios", texto: es.nav.usuarios },
];

function iniciales(nombre: string): string {
  return nombre
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

export function Shell() {
  const { usuario, cerrarSesion } = useSesion();
  return (
    <div className="shell">
      <aside className="lateral">
        <div className="logo">
          <img src={logoHonne} alt={es.comun.logoAlt} width={361} height={97} />
        </div>
        {usuario && (
          <div className="perfil">
            <div className="avatar" aria-hidden="true">{iniciales(usuario.nombre)}</div>
            <div>
              <strong>{usuario.nombre}</strong>
              <small>{usuario.rol}</small>
            </div>
          </div>
        )}
        <nav aria-label="Principal">
          {ENLACES.map((e) => (
            <NavLink key={e.a} to={e.a} end={e.fin} className={({ isActive }) => (isActive ? "activo" : undefined)}>
              {e.texto}
            </NavLink>
          ))}
        </nav>
        <button className="salir" onClick={() => void cerrarSesion()}>
          {es.comun.cerrarSesion}
        </button>
      </aside>
      <main className="principal">
        <Outlet />
      </main>
    </div>
  );
}
