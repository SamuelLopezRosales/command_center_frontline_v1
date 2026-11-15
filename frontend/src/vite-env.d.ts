/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_COGNITO_USER_POOL_ID?: string;
  readonly VITE_COGNITO_CLIENT_ID?: string;
  /** Solo desarrollo local: "true" activa el acceso de desarrollo (docs/local.md). */
  readonly VITE_AUTH_LOCAL?: string;
}
