// CSP de desarrollo: solo recursos propios (T-121). 'unsafe-inline' en estilos por Vite/TipTap.
const CSP_DESARROLLO = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self' ws://localhost:* http://localhost:*",
  "frame-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
].join("; ");

export const CABECERAS_DESARROLLO = {
  "Content-Security-Policy": CSP_DESARROLLO,
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
};
