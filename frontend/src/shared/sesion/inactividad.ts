import { useEffect, useRef } from "react";

export const INACTIVIDAD_MS = 30 * 60 * 1000;

const EVENTOS = ["mousemove", "mousedown", "keydown", "touchstart", "scroll", "click"] as const;

/** Cierra la sesión tras `limiteMs` sin actividad del usuario (CC-REQ-004). */
export function useInactividad(activo: boolean, alExpirar: () => void, limiteMs: number = INACTIVIDAD_MS) {
  const callback = useRef(alExpirar);
  callback.current = alExpirar;

  useEffect(() => {
    if (!activo) return;
    let temporizador: ReturnType<typeof setTimeout>;
    const reiniciar = () => {
      clearTimeout(temporizador);
      temporizador = setTimeout(() => callback.current(), limiteMs);
    };
    reiniciar();
    for (const e of EVENTOS) window.addEventListener(e, reiniciar, { passive: true });
    return () => {
      clearTimeout(temporizador);
      for (const e of EVENTOS) window.removeEventListener(e, reiniciar);
    };
  }, [activo, limiteMs]);
}
