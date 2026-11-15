import { useEffect, useId, useRef, type ReactNode } from "react";

interface Props {
  titulo: string;
  children: ReactNode;
  acciones: ReactNode;
  alCerrar: () => void;
}

/** Diálogo modal accesible: foco inicial y Escape para cerrar. */
export function Dialogo({ titulo, children, acciones, alCerrar }: Props) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div className="cons-fondo" onKeyDown={(e) => e.key === "Escape" && alCerrar()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={id} className="cons-dialogo">
        <h2 id={id}>{titulo}</h2>
        {children}
        <div className="cons-dialogo-acciones">{acciones}</div>
      </div>
    </div>
  );
}
