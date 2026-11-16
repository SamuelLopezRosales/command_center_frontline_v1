import { Amplify } from "aws-amplify";
import {
  confirmResetPassword,
  confirmSignIn,
  confirmSignUp,
  fetchAuthSession,
  resetPassword,
  signIn,
  signOut,
  signUp,
} from "aws-amplify/auth";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { sessionStorage as almacenSesion } from "aws-amplify/utils";
import { ErrorAcceso, type PasoAcceso, type ServicioAuth } from "./servicioAuth";

export interface ConfigCognito {
  userPoolId: string;
  userPoolClientId: string;
  /** Sin código de invitación (ambientes de prueba con registro abierto). */
  registroAbierto?: boolean;
}

function traducir(e: unknown): ErrorAcceso {
  const nombre = (e as { name?: string })?.name ?? "";
  if (nombre === "NotAuthorizedException" || nombre === "UserNotFoundException")
    return new ErrorAcceso("CREDENCIALES", "Correo o contraseña incorrectos.");
  if (nombre === "CodeMismatchException" || nombre === "ExpiredCodeException")
    return new ErrorAcceso("CODIGO_INVALIDO", "El código no es válido o venció.");
  if (nombre === "LimitExceededException" || nombre === "TooManyRequestsException")
    return new ErrorAcceso("LIMITE", "Demasiados intentos. Espera unos minutos.");
  if (nombre === "UserLambdaValidationException" || nombre === "UsernameExistsException" || nombre === "InvalidPasswordException")
    return new ErrorAcceso("REGISTRO", "No se pudo crear la cuenta. Revisa tus datos (y el código de invitación, si te lo pidieron).");
  return new ErrorAcceso("DESCONOCIDO", "No se pudo completar la operación. Intenta de nuevo.");
}

function paso(siguiente: { signInStep: string; totpSetupDetails?: { sharedSecret: string; getSetupUri: (app: string) => URL } }): PasoAcceso {
  switch (siguiente.signInStep) {
    case "CONFIRM_SIGN_IN_WITH_TOTP_CODE":
      return { paso: "TOTP" };
    case "CONTINUE_SIGN_IN_WITH_TOTP_SETUP": {
      const d = siguiente.totpSetupDetails!;
      return { paso: "ENROLAR_TOTP", uriQr: d.getSetupUri("Command Center").toString(), clave: d.sharedSecret };
    }
    case "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED":
      return { paso: "NUEVA_CONTRASENA" };
    case "DONE":
      return { paso: "LISTO" };
    default:
      throw new ErrorAcceso("DESCONOCIDO", "Paso de acceso no admitido.");
  }
}

export function crearAmplifyAuth(cfg: ConfigCognito): ServicioAuth {
  // Tokens solo en sessionStorage: se borran al cerrar la pestaña.
  cognitoUserPoolsTokenProvider.setKeyValueStorage(almacenSesion);
  Amplify.configure({ Auth: { Cognito: { userPoolId: cfg.userPoolId, userPoolClientId: cfg.userPoolClientId } } });

  return {
    registroAbierto: cfg.registroAbierto === true,
    async iniciarSesion(correo, contrasena) {
      try {
        const r = await signIn({ username: correo, password: contrasena });
        return paso(r.nextStep as never);
      } catch (e) {
        throw traducir(e);
      }
    },
    async confirmarTotp(codigo) {
      try {
        const r = await confirmSignIn({ challengeResponse: codigo });
        return paso(r.nextStep as never);
      } catch (e) {
        throw traducir(e);
      }
    },
    async registrar(d) {
      try {
        const r = await signUp({
          username: d.correo,
          password: d.contrasena,
          options: {
            userAttributes: {
              email: d.correo,
              name: d.nombre,
              // Con registro abierto no hay código: el trigger de Cognito no lo espera.
              ...(cfg.registroAbierto ? {} : { "custom:codigo_invitacion": d.codigoInvitacion ?? "" }),
            },
          },
        });
        return { requiereConfirmacion: r.nextStep.signUpStep === "CONFIRM_SIGN_UP" };
      } catch (e) {
        throw traducir(e);
      }
    },
    async confirmarRegistro(correo, codigo) {
      try {
        await confirmSignUp({ username: correo, confirmationCode: codigo });
      } catch (e) {
        throw traducir(e);
      }
    },
    async solicitarRecuperacion(correo) {
      try {
        await resetPassword({ username: correo });
      } catch (e) {
        // Sin pistas sobre si el correo existe (CC-REQ-006).
        const t = traducir(e);
        if (t.codigo === "LIMITE") throw t;
      }
    },
    async restablecerContrasena(correo, codigo, nueva) {
      try {
        await confirmResetPassword({ username: correo, confirmationCode: codigo, newPassword: nueva });
      } catch (e) {
        throw traducir(e);
      }
    },
    async haySesion() {
      try {
        return Boolean((await fetchAuthSession()).tokens?.accessToken);
      } catch {
        return false;
      }
    },
    async token() {
      try {
        return (await fetchAuthSession()).tokens?.accessToken?.toString() ?? null;
      } catch {
        return null;
      }
    },
    async cerrarSesion() {
      await signOut();
    },
  };
}
