import { useEffect } from "react";

/**
 * Las páginas públicas llevan un código o token en la ruta: que no se indexen ni se filtren por
 * Referer (CC-REQ-090, CC-REQ-084).
 */
export function usePaginaPrivada(titulo: string) {
  useEffect(() => {
    const previo = document.title;
    document.title = titulo;
    const metas = [
      ["robots", "noindex, nofollow"],
      ["referrer", "no-referrer"],
    ].map(([name, content]) => {
      const m = document.createElement("meta");
      m.name = name!;
      m.content = content!;
      document.head.appendChild(m);
      return m;
    });
    return () => {
      document.title = previo;
      metas.forEach((m) => m.remove());
    };
  }, [titulo]);
}
