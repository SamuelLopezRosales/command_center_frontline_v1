import { useState } from "react";
import { t } from "./textos";

/** URL del webhook de solo lectura: la SPA se sirve desde el mismo dominio que recibe el webhook. */
export function UrlWebhook() {
  const url = `${window.location.origin}/webhook/meta`;
  const [copia, setCopia] = useState<"ok" | "error" | null>(null);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(url);
      setCopia("ok");
    } catch {
      setCopia("error");
    }
  }

  return (
    <section className="tarjeta int-seccion" aria-labelledby="int-webhook-titulo">
      <h2 id="int-webhook-titulo">{t.webhook.titulo}</h2>
      <p className="int-suave">{t.webhook.ayuda}</p>
      <p className="int-codigo-etiqueta" id="int-webhook-etiqueta">
        {t.webhook.etiqueta}
      </p>
      <div className="int-fila">
        <code className="int-codigo" aria-labelledby="int-webhook-etiqueta">
          {url}
        </code>
        <button type="button" className="btn btn-contorno" onClick={() => void copiar()}>
          {t.webhook.copiar}
        </button>
      </div>
      {copia && (
        <p className={copia === "ok" ? "int-ok" : "alerta-error"} role="status">
          {copia === "ok" ? t.webhook.copiada : t.webhook.noCopiada}
        </p>
      )}
      <h3>{t.webhook.camposTitulo}</h3>
      <ul className="int-lista">
        {t.webhook.campos.map(([campo, nota]) => (
          <li key={campo}>
            <code>{campo}</code>: {nota}
          </li>
        ))}
      </ul>
      <p className="int-suave">{t.webhook.suscribirCuenta}</p>
    </section>
  );
}
