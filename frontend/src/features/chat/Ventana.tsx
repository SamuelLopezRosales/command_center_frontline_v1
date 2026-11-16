import { useEffect, useState } from "react";
import { msRestantes, partesDeTiempo } from "./formato";
import { t } from "./textos";

/** Reloj local que se actualiza cada minuto (el tiempo restante de la ventana avanza solo). */
export function useAhora(cadaMs = 60_000): number {
  const [ahora, setAhora] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setAhora(Date.now()), cadaMs);
    return () => clearInterval(id);
  }, [cadaMs]);
  return ahora;
}

/** Ventana efectiva: lo que dijo el servidor, salvo que el reloj local ya la dé por cerrada. */
export function ventanaAbierta(abiertaServidor: boolean, ultimoEntrante: string | null | undefined, ahora: number): boolean {
  if (!abiertaServidor) return false;
  return ultimoEntrante ? msRestantes(ultimoEntrante, ahora) > 0 : true;
}

/** Indicador visible de la ventana de 24 horas con el tiempo restante. */
export function IndicadorVentana({ abierta, ultimoEntrante, ahora }: { abierta: boolean; ultimoEntrante?: string | null; ahora: number }) {
  if (!abierta) return <span className="insignia error chat-ventana">{t.ventana.cerrada}</span>;
  const { horas, minutos } = partesDeTiempo(msRestantes(ultimoEntrante, ahora));
  const tiempo = !ultimoEntrante ? null : horas === 0 && minutos === 0 ? t.ventana.cierraEnBreve : t.ventana.horas(horas, minutos);
  return (
    <span className="chat-ventana-grupo">
      <span className="insignia ok chat-ventana">{t.ventana.abierta}</span>
      {tiempo && <span className="chat-suave">{t.ventana.queda(tiempo)}</span>}
    </span>
  );
}
