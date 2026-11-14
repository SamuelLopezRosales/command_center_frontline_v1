"""Prueba interactiva del registro, el MFA y el inicio de sesión con Cognito real (T-050).

Lo ejecuta una persona en su terminal, porque necesita tres cosas que solo ella tiene: el código
de invitación (T-049), su buzón de correo y una aplicación autenticadora (TOTP).

    $env:AWS_PROFILE = 'cc-test'
    uv run python scripts/probar_registro.py

Pasos (cada uno se detiene con un mensaje claro si falla):
 1. Registro con el código de invitación (dispara ``cognito-pre-signup``).
 2. Confirmación del correo con el código que envía Cognito (``cognito-post-confirmation`` crea el
    usuario RH en la base).
 3. Primer inicio de sesión: SRP y alta del TOTP (reto ``MFA_SETUP``).
 4. Segundo inicio de sesión: SRP y código TOTP (reto ``SOFTWARE_TOKEN_MFA``).
 5. El token de acceso trae ``empresa_id`` y ``rol = RH`` (``cognito-pre-token``).
 6. El mismo código de invitación ya no sirve para otro registro.
 7. La recuperación de contraseña envía un correo.

Nunca se imprimen la contraseña, el código de invitación ni los tokens. El secreto del TOTP se
muestra una vez, en esta terminal, para darlo de alta en la aplicación autenticadora.
"""

from __future__ import annotations

import base64
import getpass
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

REGION = "us-east-1"
PERFIL = "cc-test"
CUENTA = "034362033822"
STACK_AUTH = "CcAuth-test"
EMISOR_TOTP = "Command Center (test)"


class PruebaFallida(Exception):  # noqa: N818
    pass


@dataclass(frozen=True)
class Destino:
    pool_id: str
    cliente_id: str


def paso(n: int, texto: str) -> None:
    print(f"\n[{n}] {texto}")


def ok(texto: str) -> None:
    print(f"    OK  {texto}")


def _aws(*argumentos: str) -> dict[str, Any]:
    """CLI de AWS con el perfil cc-test: admite las credenciales de ``aws login`` sin más
    dependencias (boto3 necesitaría ``botocore[crt]``)."""
    aws = shutil.which("aws")
    if not aws:
        raise PruebaFallida("No se encontró la CLI de AWS.")
    r = subprocess.run(  # noqa: S603
        [aws, *argumentos, "--profile", PERFIL, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise PruebaFallida(
            "La CLI de AWS falló. Si la sesión venció: aws login --profile cc-test "
            f"--region us-east-1 ({r.stderr.strip()[:200]})"
        )
    return json.loads(r.stdout)


def destino() -> Destino:
    """Lee el grupo y el cliente de las salidas de CcAuth-test, tras comprobar la cuenta."""
    cuenta = _aws("sts", "get-caller-identity")["Account"]
    if cuenta != CUENTA:
        raise PruebaFallida(f"La sesión es de la cuenta {cuenta}, no de {CUENTA}.")
    pila = _aws("cloudformation", "describe-stacks", "--stack-name", STACK_AUTH)["Stacks"][0]
    salidas = {o["OutputKey"]: o["OutputValue"] for o in pila["Outputs"]}
    return Destino(salidas["UserPoolId"], salidas["ClienteSpaId"])


def cliente_cognito() -> Any:
    """Las operaciones de usuario de Cognito no usan credenciales de AWS: se firman sin ellas."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client(
        "cognito-idp", region_name=REGION, config=Config(signature_version=UNSIGNED)
    )


def claims_sin_verificar(token: str) -> dict[str, Any]:
    """Lee las afirmaciones del JWT para mostrarlas. La firma la valida Cognito y la API."""
    carga = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))


def pedir(texto: str, *, oculto: bool = False) -> str:
    valor = (getpass.getpass(f"    {texto}: ") if oculto else input(f"    {texto}: ")).strip()
    if not valor:
        raise PruebaFallida(f"Falta: {texto}")
    return valor


def iniciar_srp(cog: Any, d: Destino, correo: str, clave: str) -> tuple[dict[str, Any], str]:
    """Hace el intercambio SRP y devuelve la respuesta del siguiente reto y el usuario interno."""
    from pycognito.aws_srp import AWSSRP

    srp = AWSSRP(
        username=correo, password=clave, pool_id=d.pool_id, client_id=d.cliente_id, client=cog
    )
    params = srp.get_auth_params()
    r = cog.initiate_auth(AuthFlow="USER_SRP_AUTH", ClientId=d.cliente_id, AuthParameters=params)
    if r.get("ChallengeName") != "PASSWORD_VERIFIER":
        raise PruebaFallida(f"Se esperaba PASSWORD_VERIFIER y llegó {r.get('ChallengeName')}.")
    respuestas = srp.process_challenge(r["ChallengeParameters"], params)
    r2 = cog.respond_to_auth_challenge(
        ClientId=d.cliente_id, ChallengeName="PASSWORD_VERIFIER", ChallengeResponses=respuestas
    )
    return r2, r["ChallengeParameters"].get("USER_ID_FOR_SRP", correo)


def alta_totp(cog: Any, d: Destino, r: dict[str, Any], usuario: str, correo: str) -> dict:
    if r.get("ChallengeName") != "MFA_SETUP":
        raise PruebaFallida(f"Se esperaba MFA_SETUP y llegó {r.get('ChallengeName')}.")
    alta = cog.associate_software_token(Session=r["Session"])
    secreto = alta["SecretCode"]
    uri = (
        f"otpauth://totp/{quote(EMISOR_TOTP)}:{quote(correo)}?secret={secreto}"
        f"&issuer={quote(EMISOR_TOTP)}"
    )
    print("\n    Da de alta esta cuenta en tu aplicación autenticadora (se muestra una sola vez):")
    try:
        import segno

        segno.make(uri, error="m").terminal(compact=True)
    except Exception:  # noqa: BLE001 - el código QR es opcional
        print("    (No se pudo dibujar el código QR; usa la clave.)")
    print(f"    Clave para escribirla a mano: {secreto}")
    codigo = pedir("Código de 6 dígitos que muestra la aplicación")
    v = cog.verify_software_token(
        Session=alta["Session"], UserCode=codigo, FriendlyDeviceName="prueba-t050"
    )
    if v.get("Status") != "SUCCESS":
        raise PruebaFallida("Cognito no aceptó el código TOTP.")
    r2 = cog.respond_to_auth_challenge(
        ClientId=d.cliente_id,
        ChallengeName="MFA_SETUP",
        Session=v["Session"],
        ChallengeResponses={"USERNAME": usuario},
    )
    return r2


def responder_totp(cog: Any, d: Destino, r: dict[str, Any], usuario: str) -> dict:
    if r.get("ChallengeName") != "SOFTWARE_TOKEN_MFA":
        raise PruebaFallida(f"Se esperaba SOFTWARE_TOKEN_MFA y llegó {r.get('ChallengeName')}.")
    codigo = pedir("Código TOTP actual (espera a que cambie si acabas de usar el anterior)")
    return cog.respond_to_auth_challenge(
        ClientId=d.cliente_id,
        ChallengeName="SOFTWARE_TOKEN_MFA",
        Session=r["Session"],
        ChallengeResponses={"USERNAME": usuario, "SOFTWARE_TOKEN_MFA_CODE": codigo},
    )


def revisar_token(r: dict[str, Any]) -> dict[str, Any]:
    tokens = r.get("AuthenticationResult")
    if not tokens:
        raise PruebaFallida(f"No llegaron tokens (reto: {r.get('ChallengeName')}).")
    c = claims_sin_verificar(tokens["AccessToken"])
    if c.get("token_use") != "access":
        raise PruebaFallida("El token no es de acceso.")
    if c.get("rol") != "RH" or not str(c.get("empresa_id", "")).isdigit():
        raise PruebaFallida(
            f"El token de acceso no trae empresa_id y rol=RH (empresa_id={c.get('empresa_id')}, "
            f"rol={c.get('rol')}). Revise la Lambda cognito-pre-token."
        )
    return c


def main() -> int:
    from botocore.exceptions import ClientError

    print("Prueba de registro, MFA e inicio de sesión (T-050). Ctrl+C para cancelar.")
    try:
        d = destino()
        print(f"Grupo {d.pool_id}, cliente {d.cliente_id}.")
        cog = cliente_cognito()

        paso(1, "Registro con el código de invitación")
        correo = pedir("Correo (recibirás un código)").lower()
        nombre = pedir("Nombre completo")
        clave = pedir(
            "Contraseña nueva (12+ caracteres: mayúscula, minúscula, número y símbolo)", oculto=True
        )
        if pedir("Repite la contraseña", oculto=True) != clave:
            raise PruebaFallida("Las contraseñas no coinciden.")
        codigo_inv = pedir("Código de invitación de T-049", oculto=True)
        cog.sign_up(
            ClientId=d.cliente_id,
            Username=correo,
            Password=clave,
            UserAttributes=[
                {"Name": "email", "Value": correo},
                {"Name": "name", "Value": nombre},
                {"Name": "custom:codigo_invitacion", "Value": codigo_inv},
            ],
        )
        ok("Registro aceptado por cognito-pre-signup.")

        paso(2, "Confirmación del correo")
        cog.confirm_sign_up(
            ClientId=d.cliente_id,
            Username=correo,
            ConfirmationCode=pedir("Código que llegó a tu correo"),
        )
        ok("Correo confirmado; cognito-post-confirmation creó el usuario RH.")

        paso(3, "Primer inicio de sesión y alta del TOTP")
        r, usuario = iniciar_srp(cog, d, correo, clave)
        c = revisar_token(alta_totp(cog, d, r, usuario, correo))
        ok(f"Sesión iniciada. Token de acceso: empresa_id={c['empresa_id']}, rol={c['rol']}.")

        paso(4, "Segundo inicio de sesión: debe pedir el código TOTP")
        r, usuario = iniciar_srp(cog, d, correo, clave)
        c = revisar_token(responder_totp(cog, d, r, usuario))
        ok(
            f"Cognito exigió el TOTP. empresa_id={c['empresa_id']}, rol={c['rol']}, "
            f"vigencia {(c['exp'] - c['iat']) // 60} min."
        )

        paso(5, "El código de invitación ya usado se rechaza")
        nombre_local, dominio = correo.split("@", 1)
        otro = f"{nombre_local}+reuso-t050@{dominio}"
        try:
            cog.sign_up(
                ClientId=d.cliente_id,
                Username=otro,
                Password=clave,
                UserAttributes=[
                    {"Name": "email", "Value": otro},
                    {"Name": "name", "Value": "Prueba de reuso"},
                    {"Name": "custom:codigo_invitacion", "Value": codigo_inv},
                ],
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "UserLambdaValidationException":
                raise
            ok("Rechazado por cognito-pre-signup con el mensaje genérico.")
        else:
            raise PruebaFallida(f"El código usado permitió registrar {otro}: revise pre-signup.")

        paso(6, "Recuperación de contraseña")
        r = cog.forgot_password(ClientId=d.cliente_id, Username=correo)
        envio = r.get("CodeDeliveryDetails", {})
        medio, a_donde = envio.get("DeliveryMedium"), envio.get("Destination")
        ok(
            f"Cognito envió el código por {medio} a {a_donde}"
            " (no hace falta usarlo; tu contraseña no cambia)."
        )
    except PruebaFallida as exc:
        print(f"\nFALLA: {exc}")
        return 1
    except ClientError as exc:
        e = exc.response["Error"]
        print(f"\nFALLA: Cognito respondió {e['Code']}: {e.get('Message', '')[:200]}")
        return 1
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 130

    print("\nPrueba completa: registro, MFA, inicio de sesión, claims, reuso y recuperación.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
