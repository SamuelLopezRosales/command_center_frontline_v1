"""Stack local: el secreto de Meta de LocalStack y la configuración de `notificaciones`."""

import json

from scripts.local import constantes as c
from scripts.local.stack import entorno_servicio


def test_notificaciones_local_guarda_credenciales_en_localstack_y_deja_las_plantillas_sin_red():
    secretos = {"roles": {}}
    env = entorno_servicio("notificaciones", secretos)
    assert env["CC_META_SECRETO_ID"] == c.SECRETO_META == "cc/local/meta"
    assert env["CC_META_PLANTILLAS_STUB"] == "true"
    # Todo el SDK va a LocalStack: nada llega a AWS.
    assert env["AWS_ENDPOINT_URL"] == c.LOCALSTACK


def test_el_secreto_local_se_crea_vacio_y_no_se_reescribe():
    from botocore.exceptions import ClientError

    from scripts.local.aprovisionar import crear_secreto_meta

    class Sm:
        def __init__(self):
            self.secretos: dict[str, str] = {}
            self.puts = 0

        def create_secret(self, Name, SecretString):  # noqa: N803
            if Name in self.secretos:
                raise ClientError({"Error": {"Code": "ResourceExistsException"}}, "CreateSecret")
            self.secretos[Name] = SecretString

        def put_secret_value(self, SecretId, SecretString):  # noqa: N803
            self.puts += 1
            self.secretos[SecretId] = SecretString

    sm = Sm()
    assert crear_secreto_meta(sm, lambda *_: None) is True
    assert json.loads(sm.secretos[c.SECRETO_META]) == {}
    # Se capturaron credenciales desde la pantalla: reprovisionar no las borra.
    sm.secretos[c.SECRETO_META] = '{"waba_id": "12345678"}'
    assert crear_secreto_meta(sm, lambda *_: None) is False
    assert sm.puts == 0 and json.loads(sm.secretos[c.SECRETO_META]) == {"waba_id": "12345678"}
