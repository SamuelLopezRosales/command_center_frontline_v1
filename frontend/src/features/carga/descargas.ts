import { leerProblema } from "@/shared/errores";

/**
 * Descarga un archivo protegido por token (plantilla `.xlsx`, reporte `.csv`): se pide con el
 * encabezado Authorization y se entrega al navegador como descarga. El token nunca va en la URL.
 */
export async function descargarArchivo(ruta: string, nombre: string, token: string | null): Promise<void> {
  const r = await fetch(ruta, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) throw await leerProblema(r);
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = nombre;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
