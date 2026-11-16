// Frontera con Cognito. Las pantallas dependen de esta interfaz, no de Amplify, para poder
// probarlas con un Cognito simulado. Los tokens viven solo en sessionStorage (T-120).
export type PasoAcceso =
  | { paso: "TOTP" }
  | { paso: "ENROLAR_TOTP"; uriQr: string; clave: string }
  | { paso: "NUEVA_CONTRASENA" }
  | { paso: "LISTO" };

export interface DatosRegistro {
  nombre: string;
  correo: string;
  contrasena: string;
  /** Obligatorio salvo que `registroAbierto` sea verdadero. */
  codigoInvitacion?: string;
}

export interface ServicioAuth {
  /** Registro sin código de invitación (ambientes de prueba). */
  registroAbierto?: boolean;
  iniciarSesion(correo: string, contrasena: string): Promise<PasoAcceso>;
  confirmarTotp(codigo: string): Promise<PasoAcceso>;
  registrar(datos: DatosRegistro): Promise<{ requiereConfirmacion: boolean }>;
  confirmarRegistro(correo: string, codigo: string): Promise<void>;
  solicitarRecuperacion(correo: string): Promise<void>;
  restablecerContrasena(correo: string, codigo: string, nueva: string): Promise<void>;
  haySesion(): Promise<boolean>;
  token(): Promise<string | null>;
  cerrarSesion(): Promise<void>;
}

export class ErrorAcceso extends Error {
  constructor(
    readonly codigo: "CREDENCIALES" | "CODIGO_INVALIDO" | "REGISTRO" | "LIMITE" | "DESCONOCIDO",
    mensaje: string,
  ) {
    super(mensaje);
    this.name = "ErrorAcceso";
  }
}
