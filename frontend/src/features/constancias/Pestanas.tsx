import { useQuery } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { listarPlantillas } from "./api";
import { t } from "./textos";

/** Pestañas Plantillas / Historial (cv1_05 y cv1_07). */
export function Pestanas() {
  const plantillas = useQuery({ queryKey: ["constancias", "plantillas"], queryFn: listarPlantillas });
  const total = plantillas.data ? ` (${plantillas.data.length})` : "";
  return (
    <nav className="cons-pestanas" aria-label={t.pestanas.aria}>
      <NavLink to="/constancias" end className={({ isActive }) => (isActive ? "activa" : undefined)}>
        {t.pestanas.plantillas}
        {total}
      </NavLink>
      <NavLink to="/constancias/historial" className={({ isActive }) => (isActive ? "activa" : undefined)}>
        {t.pestanas.historial}
      </NavLink>
    </nav>
  );
}
