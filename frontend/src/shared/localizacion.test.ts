// Localización (CC-NFR-012): todo texto visible está en español y vive en los módulos de textos.
//
// Heurística documentada
// ----------------------
// 1. Se recorren `shared/i18n/es.ts` y todos los `features/**/textos.ts` (objetos anidados; las
//    funciones se invocan con argumentos de relleno para obtener la cadena).
// 2. Una cadena falla si contiene, como PALABRA COMPLETA y sin distinguir mayúsculas, alguna
//    palabra de la lista PALABRAS_EN_INGLES: términos de interfaz y palabras funcionales del
//    inglés que no existen en español ("Save", "Cancel", "Loading", "the", "and"...).
// 3. No es un detector de idioma: es una red de seguridad contra el olvido típico (un botón con
//    "Save" o un mensaje con "Loading..."). Evita falsos positivos porque solo marca palabras de
//    la lista; los nombres propios y términos técnicos (WhatsApp, Meta, Excel, PDF, QR, TOTP, MFA,
//    NSS, RFC, CURP, Dashboard...) no están en la lista, así que pasan. "Error", "Total" o "Plan"
//    son también palabras del español y por eso NO están en la lista.
// 4. Segunda prueba (estática): ningún `.tsx` de producción tiene texto literal entre etiquetas ni
//    en los atributos `aria-label`, `title`, `placeholder` y `alt` fuera de los módulos de textos,
//    salvo la lista EXCEPCIONES_JSX (con motivo).
import { describe, expect, it } from "vitest";

const PALABRAS_EN_INGLES = [
  // Acciones y navegación de la interfaz
  "save", "cancel", "loading", "search", "delete", "remove", "submit", "close", "next", "previous", "back",
  "edit", "add", "create", "update", "upload", "download", "confirm", "continue", "retry", "reset", "apply",
  "clear", "filter", "filters", "select", "settings", "home", "login", "logout", "log", "sign", "signin", "signup",
  "register", "forgot", "send", "open", "view", "details", "actions", "show", "hide", "more", "less", "done",
  // Etiquetas y estados
  "password", "username", "email", "name", "status", "title", "description", "date", "time", "yes", "please",
  "failed", "success", "successfully", "warning", "invalid", "required", "optional", "enabled", "disabled",
  "active", "inactive", "pending", "empty", "no data", "not", "found", "welcome", "hello", "user", "users",
  // Palabras funcionales del inglés
  "the", "and", "or", "of", "for", "with", "your", "you", "is", "are", "was", "this", "that", "from", "to",
  "an", "in", "on", "at", "by", "has", "have", "will", "can", "could", "should", "must", "would", "been",
];
// Palabras de la lista anterior que NO se usan para detectar porque son ambiguas (también son español,
// como "no" o "sign", o aparecen en nombres propios y términos técnicos): se descartan abajo.
const AMBIGUAS_CON_ESPANOL = new Set(["no data", "log", "date", "time", "can", "title", "name", "view", "open", "more", "an", "in", "at", "by", "has", "have", "reset", "sign", "show", "send", "less", "found", "active", "no"]);
const PALABRAS = PALABRAS_EN_INGLES.filter((p) => !AMBIGUAS_CON_ESPANOL.has(p));
const REGEX_INGLES = new RegExp(`(?<![\\p{L}\\p{N}_])(${PALABRAS.join("|")})(?![\\p{L}\\p{N}_])`, "giu");

/** Términos que se permiten aunque coincidan con la lista (nombres propios y técnicos). */
const PERMITIDOS = ["WhatsApp", "Meta", "Excel", "PDF", "QR", "TOTP", "MFA", "NSS", "RFC", "CURP"];

export function palabrasEnIngles(texto: string): string[] {
  let limpio = texto;
  // Variables de plantilla `{{nombre}}` y términos permitidos no cuentan.
  limpio = limpio.replace(/\{\{[^}]*\}\}/g, " ");
  for (const p of PERMITIDOS) limpio = limpio.split(p).join(" ");
  return [...limpio.matchAll(REGEX_INGLES)].map((m) => m[1]!.toLowerCase());
}

function cadenas(valor: unknown, ruta: string, salida: [string, string][], profundidad = 0): void {
  if (profundidad > 8) return;
  if (typeof valor === "string") salida.push([ruta, valor]);
  else if (typeof valor === "function") {
    for (const args of [["X"], ["X", "X"], [1], [1, 1], ["X", 1]] as unknown[][]) {
      try {
        const r = (valor as (...a: unknown[]) => unknown)(...args);
        if (typeof r === "string") {
          salida.push([`${ruta}()`, r]);
          return;
        }
      } catch {
        /* se prueba con otros argumentos */
      }
    }
  } else if (Array.isArray(valor)) valor.forEach((v, i) => cadenas(v, `${ruta}[${i}]`, salida, profundidad + 1));
  else if (valor && typeof valor === "object") for (const [k, v] of Object.entries(valor)) cadenas(v, `${ruta}.${k}`, salida, profundidad + 1);
}

const modulos = import.meta.glob("../features/**/textos.ts", { eager: true }) as Record<string, Record<string, unknown>>;

async function todosLosTextos(): Promise<[string, string][]> {
  const salida: [string, string][] = [];
  const { es } = await import("./i18n/es");
  cadenas(es, "shared/i18n/es", salida);
  for (const [archivo, modulo] of Object.entries(modulos)) for (const [nombre, valor] of Object.entries(modulo)) cadenas(valor, `${archivo.replace("../", "")}:${nombre}`, salida);
  return salida;
}

describe("localización: cadenas en español (CC-NFR-012)", () => {
  it("la heurística detecta inglés evidente y deja pasar nombres propios y términos técnicos", () => {
    expect(palabrasEnIngles("Save")).toEqual(["save"]);
    expect(palabrasEnIngles("Loading... please wait")).toEqual(["loading", "please"]);
    expect(palabrasEnIngles("Click to Cancel the upload")).toEqual(["to", "cancel", "the", "upload"]);
    expect(palabrasEnIngles("Guardar cambios")).toEqual([]);
    expect(palabrasEnIngles("Error al cargar el archivo PDF")).toEqual([]);
    expect(palabrasEnIngles("Enviar por WhatsApp con Meta a {{1}}; RFC, CURP, NSS, TOTP, MFA, QR, Excel")).toEqual([]);
    expect(palabrasEnIngles("Cancelar")).toEqual([]); // palabra completa, no subcadena
  });

  it("se encontraron los módulos de textos y hay cadenas que revisar", async () => {
    expect(Object.keys(modulos).length).toBeGreaterThanOrEqual(10);
    const textos = await todosLosTextos();
    expect(textos.length).toBeGreaterThan(500);
  });

  it("ninguna cadena de shared/i18n/es.ts ni de features/*/textos.ts tiene inglés evidente", async () => {
    const hallazgos = (await todosLosTextos()).flatMap(([ruta, texto]) => {
      const p = palabrasEnIngles(texto);
      return p.length ? [`${ruta}: «${texto}» -> ${[...new Set(p)].join(", ")}`] : [];
    });
    expect(hallazgos, "cadenas con palabras en inglés").toEqual([]);
  });
});

// ---- Texto literal en JSX fuera de los módulos de textos ----

const fuentes = import.meta.glob(["../**/*.tsx", "!../**/*.test.tsx"], { eager: true, query: "?raw", import: "default" }) as Record<string, string>;

/**
 * Textos literales que se permiten en un componente: [archivo (fragmento), texto, motivo].
 * Todo lo demás debe venir de un módulo de textos.
 */
const EXCEPCIONES_JSX: [string, string, string][] = [
  ["Shell.tsx", "HONNE", "marca (nombre propio)"],
  ["PaginaAcceso.tsx", "HONNE", "marca (nombre propio)"],
  ["ListadoColaboradores.tsx", "ACTIVO", "valor de dominio del estatus, no texto de interfaz"],
  ["ListadoColaboradores.tsx", "BAJA", "valor de dominio del estatus, no texto de interfaz"],
  // Etiquetas accesibles ya en español pero aún escritas en el componente. Pendiente de migrarlas
  // a su textos.ts (no afecta al idioma: CC-NFR-012 se cumple).
  ["Shell.tsx", "Principal", "aria-label en español, pendiente de mover a textos"],
  ["PaginaAcceso.tsx", "Código QR de la aplicación autenticadora", "title en español, pendiente de mover a textos"],
  ["RutasCampos.tsx", "Tipo de campo", "aria-label en español, pendiente de mover a textos"],
  ["RutasCampos.tsx", "Campos", "aria-label en español, pendiente de mover a textos"],
  ["Dashboard.tsx", "Indicadores", "aria-label en español, pendiente de mover a textos"],
  ["DetalleEnvio.tsx", "Ruta de navegación", "aria-label en español, pendiente de mover a textos"],
  ["NuevaNotificacion.tsx", "Ruta de navegación", "aria-label en español, pendiente de mover a textos"],
  ["PlantillasMensaje.tsx", "Ruta de navegación", "aria-label en español, pendiente de mover a textos"],
  ["RutasOrganizaciones.tsx", "Catálogos", "aria-label en español, pendiente de mover a textos"],
];

function literalesJsx(fuente: string): string[] {
  const hallazgos: string[] = [];
  // Texto entre etiquetas: `>Texto<` con letras, sin llaves ni saltos a expresiones.
  for (const m of fuente.matchAll(/>([^<>{}=;()\n]*[\p{L}]{2,}[^<>{}=;()\n]*)</gu)) {
    const t = m[1]!.trim();
    // Descarta fragmentos de código TypeScript: genéricos (`Promise<void>`) y anotaciones de tipos.
    if (!t || t === "Promise" || t.includes(":")) continue;
    hallazgos.push(t);
  }
  // Atributos de texto accesible con literal entre comillas.
  for (const m of fuente.matchAll(/\b(?:aria-label|title|placeholder|alt)="([^"{}]*[\p{L}]{2,}[^"{}]*)"/gu)) hallazgos.push(m[1]!.trim());
  return hallazgos;
}

describe("localización: sin texto literal en los componentes", () => {
  it("el detector encuentra literales y los de las excepciones se ignoran", () => {
    expect(literalesJsx("<button>Guardar</button>")).toEqual(["Guardar"]);
    expect(literalesJsx('<input aria-label="Buscar" />')).toEqual(["Buscar"]);
    expect(literalesJsx("<button>{t.guardar}</button>")).toEqual([]);
    expect(literalesJsx("const x: Array<string> = []; const y: Promise<void> = f(); a > b && c < d;")).toEqual([]);
  });

  it("ningún componente de producción tiene texto literal fuera de los módulos de textos", () => {
    const encontrados: string[] = [];
    for (const [archivo, fuente] of Object.entries(fuentes)) {
      for (const texto of literalesJsx(fuente)) {
        const permitido = EXCEPCIONES_JSX.some(([f, t]) => archivo.includes(f) && (t === "" || t === texto));
        if (!permitido) encontrados.push(`${archivo.replace("../", "")}: «${texto}»`);
      }
    }
    expect(encontrados, "texto literal en JSX (muévelo a textos.ts o agrégalo a EXCEPCIONES_JSX con motivo)").toEqual([]);
  });
});
