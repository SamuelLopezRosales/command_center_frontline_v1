"""Ayudantes de las pruebas de la conexión con Meta: dobles sin Docker ni AWS.

- ``ClienteSecretosFalso``: lo que usa ``AlmacenSecretsManager`` de boto3 (``get_secret_value`` y
  ``put_secret_value``) sobre una cadena en memoria.
- ``MotorFalso``: el motor asíncrono de SQLAlchemy reducido a ``begin()``; anota las sentencias
  (candado, ``set_config``, inserción en la bitácora) para comprobarlas sin base de datos.
"""

import contextlib
import json
import re

# Valores de prueba reconocibles: si aparecen en una respuesta o un log, la prueba lo detecta.
ACCESS_TOKEN = "EAAGprueba0123456789tokenSecretoUNICOzz"  # pragma: allowlist secret
APP_SECRET = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret
VERIFY_TOKEN = "verify_token_de_prueba_0001"  # pragma: allowlist secret
WABA_ID = "9876543210987654"
PHONE_NUMBER_ID = "1234567890123456"
SECRETOS = (ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN)

# Lo que crea CcSecurity al desplegar (más ``_marcador``, la cadena aleatoria de la plantilla).
VALOR_INICIAL_CDK = json.dumps(
    {
        "phone_number_id": "",
        "waba_id": "",
        "token": "",
        "verify_token": "",
        "graph_version": "",
        "_marcador": "aleatorio",
    }
)

COMPLETO = {
    "waba_id": WABA_ID,
    "phone_number_id": PHONE_NUMBER_ID,
    "access_token": ACCESS_TOKEN,
    "app_secret": APP_SECRET,
    "verify_token": VERIFY_TOKEN,
}


class ClienteSecretosFalso:
    def __init__(self, valor: str | None = VALOR_INICIAL_CDK) -> None:
        self.valor = valor
        self.escrituras: list[str] = []
        self.falla_escritura = False
        self.lecturas = 0

    def get_secret_value(self, SecretId):  # noqa: N803
        self.lecturas += 1
        return {"SecretString": self.valor, "Name": SecretId}

    def put_secret_value(self, SecretId, SecretString):  # noqa: N803
        if self.falla_escritura:
            raise RuntimeError(f"AccessDenied para {SecretId}")
        self.valor = SecretString
        self.escrituras.append(SecretString)

    @property
    def json(self) -> dict:
        return json.loads(self.valor)


class _Resultado:
    def fetchone(self):
        return None


class _Conexion:
    def __init__(self, sentencias: list) -> None:
        self._sentencias = sentencias

    async def execute(self, sentencia, params=None):
        self._sentencias.append((str(sentencia), dict(params or {})))
        return _Resultado()


class MotorFalso:
    def __init__(self) -> None:
        self.sentencias: list[tuple[str, dict]] = []
        self.transacciones = 0
        self.revertidas = 0

    @contextlib.asynccontextmanager
    async def begin(self):
        self.transacciones += 1
        try:
            yield _Conexion(self.sentencias)
        except BaseException:
            self.revertidas += 1
            raise

    async def dispose(self) -> None:
        return None

    def bitacora(self) -> list[dict]:
        """Registros que se habrían insertado: acción, usuario y detalle."""
        return [
            {
                "accion": p["accion"],
                "usuario_id": p["usuario_id"],
                "empresa_id": p["empresa_id"],
                "entidad": p["entidad"],
                "detalle": json.loads(p["detalle"]),
            }
            for s, p in self.sentencias
            if "auditoria.bitacora" in s
        ]

    def candados(self) -> int:
        return sum(1 for s, _ in self.sentencias if "pg_advisory_xact_lock" in s)


def sin_secretos(texto: str) -> bool:
    """Ninguno de los valores secretos de prueba aparece en ``texto``."""
    return not any(s in texto for s in SECRETOS)


PATRON_TOKEN_VERIFICACION = re.compile(r"^[A-Za-z0-9_-]{32,}$")
