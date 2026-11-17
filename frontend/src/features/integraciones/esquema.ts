import { z } from "zod";
import { t } from "./textos";

/** Un campo opcional: vacío significa «no cambiar»; si trae algo, debe cumplir el formato. */
const opcional = (patron: RegExp, mensaje: string) =>
  z
    .string()
    .trim()
    .refine((v) => v === "" || patron.test(v), mensaje);

// Mismos formatos que valida el servidor (integracion_meta.py).
export const RE_ID_META = /^\d{8,25}$/;
export const RE_VERSION = /^v\d{1,3}\.\d{1,2}$/;
export const RE_TOKEN_ACCESO = /^\S{20,1000}$/;
export const RE_APP_SECRET = /^[0-9a-fA-F]{32}$/;
export const RE_VERIFY_TOKEN = /^[A-Za-z0-9_-]{16,128}$/;

export const esquemaMeta = z.object({
  waba_id: opcional(RE_ID_META, t.errores.id),
  phone_number_id: opcional(RE_ID_META, t.errores.id),
  api_version: opcional(RE_VERSION, t.errores.version),
  access_token: opcional(RE_TOKEN_ACCESO, t.errores.tokenAcceso),
  app_secret: opcional(RE_APP_SECRET, t.errores.appSecret),
  verify_token: opcional(RE_VERIFY_TOKEN, t.errores.verifyToken),
});
export type ValoresMeta = z.infer<typeof esquemaMeta>;
export type CampoMeta = keyof ValoresMeta;

export const CAMPOS_SECRETOS: CampoMeta[] = ["access_token", "app_secret", "verify_token"];
