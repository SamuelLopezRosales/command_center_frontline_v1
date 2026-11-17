import { useEffect, useId, useRef, type ReactNode } from "react";

interface Props {
  titulo: string;
  children: ReactNode;
  acciones: ReactNode;
  alCerrar: () => void;
}

/** Diálogo modal accesible: foco inicial y Escape para cerrar. No se cierra al hacer clic fuera. */
export function Dialogo({ titulo, children, acciones, alCerrar }: Props) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div className="int-fondo" onKeyDown={(e) => e.key === "Escape" && alCerrar()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={id} className="int-dialogo">
        <h2 id={id}>{titulo}</h2>
        {children}
        <div className="int-dialogo-acciones">{acciones}</div>
      </div>
    </div>
  );
}
