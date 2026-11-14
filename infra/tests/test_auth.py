"""T-042: aserciones del stack CcAuth."""

import json

import pytest
from aws_cdk.assertions import Template

from infra.app import construir_stacks, crear_app

PERMITIDA = "034362033822"


@pytest.fixture(scope="module")
def plantilla() -> Template:
    app, amb, destino = crear_app("test", {"CDK_DEFAULT_ACCOUNT": PERMITIDA})
    return Template.from_stack(construir_stacks(app, amb, destino)["auth"])


def _pool(plantilla) -> dict:
    (p,) = plantilla.find_resources("AWS::Cognito::UserPool").values()
    return p["Properties"]


def _cliente(plantilla) -> dict:
    (c,) = plantilla.find_resources("AWS::Cognito::UserPoolClient").values()
    return c["Properties"]


def test_mfa_obligatorio_solo_con_totp_y_sin_sms(plantilla):
    p = _pool(plantilla)
    assert p["MfaConfiguration"] == "ON"
    assert p["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]
    assert "SmsConfiguration" not in p
    plantilla.resource_count_is("AWS::Cognito::UserPoolDomain", 0)


def test_contrasena_de_12_caracteres_con_las_cuatro_clases(plantilla):
    pol = _pool(plantilla)["Policies"]["PasswordPolicy"]
    assert pol["MinimumLength"] == 12
    assert pol["RequireLowercase"] and pol["RequireUppercase"]
    assert pol["RequireNumbers"] and pol["RequireSymbols"]


def test_tokens_de_15_minutos_y_actualizacion_de_8_horas_con_rotacion(plantilla):
    c = _cliente(plantilla)
    assert c["AccessTokenValidity"] == 15 and c["IdTokenValidity"] == 15
    assert c["RefreshTokenValidity"] == 480  # minutos
    assert c["TokenValidityUnits"] == {
        "AccessToken": "minutes",
        "IdToken": "minutes",
        "RefreshToken": "minutes",
    }
    assert c["RefreshTokenRotation"]["Feature"] == "ENABLED"
    assert c["EnableTokenRevocation"] is True


def test_cliente_publico_solo_srp_sin_oauth_y_sin_revelar_usuarios(plantilla):
    c = _cliente(plantilla)
    assert c["GenerateSecret"] is False
    # Cognito siempre admite la renovación con el token de actualización; solo SRP para entrar.
    assert c["ExplicitAuthFlows"] == ["ALLOW_USER_SRP_AUTH"]
    assert c["PreventUserExistenceErrors"] == "ENABLED"
    assert not c.get("AllowedOAuthFlowsUserPoolClient")


def test_el_cliente_escribe_el_codigo_pero_no_lo_lee(plantilla):
    c = _cliente(plantilla)
    assert "custom:codigo_invitacion" in c["WriteAttributes"]
    assert "custom:codigo_invitacion" not in c["ReadAttributes"]
    assert "email" in c["WriteAttributes"] and "name" in c["WriteAttributes"]


def test_atributo_personalizado_del_codigo(plantilla):
    esquema = {a["Name"]: a for a in _pool(plantilla)["Schema"]}
    assert esquema["codigo_invitacion"]["Mutable"] is True
    assert esquema["email"]["Required"] is True and esquema["email"]["Mutable"] is False


def test_registro_propio_habilitado_con_el_trigger_de_pre_registro(plantilla):
    p = _pool(plantilla)
    assert p["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is False
    triggers = p["LambdaConfig"]
    assert "PreSignUp" in triggers and "PostConfirmation" in triggers
    assert "Alias" in json.dumps(triggers["PreSignUp"])
    assert "Alias" in json.dumps(triggers["PostConfirmation"])
    assert triggers["PreTokenGenerationConfig"]["LambdaVersion"] == "V2_0"


def test_los_triggers_apuntan_al_alias_live(plantilla):
    alias = plantilla.find_resources("AWS::Lambda::Alias")
    assert len(alias) == 3
    for a in alias.values():
        assert a["Properties"]["Name"] == "live"
    # Cognito invoca el alias, no $LATEST: revertir es mover el alias.
    for permiso in plantilla.find_resources("AWS::Lambda::Permission").values():
        assert permiso["Properties"]["Principal"] == "cognito-idp.amazonaws.com"
        assert "Alias" in json.dumps(permiso["Properties"]["FunctionName"])


def test_recuperacion_de_contrasena_por_correo(plantilla):
    p = _pool(plantilla)
    assert p["AccountRecoverySetting"]["RecoveryMechanisms"] == [
        {"Name": "verified_email", "Priority": 1}
    ]
    assert p["AutoVerifiedAttributes"] == ["email"]
    assert p["UsernameAttributes"] == ["email"]


def test_plan_de_funciones_essentials(plantilla):
    assert _pool(plantilla)["UserPoolTier"] == "ESSENTIALS"


def test_grupo_borrable_en_test(plantilla):
    (p,) = plantilla.find_resources("AWS::Cognito::UserPool").values()
    assert p["DeletionPolicy"] == "Delete"
    assert p["Properties"].get("DeletionProtection") in (None, "INACTIVE")


def test_tres_lambdas_en_la_vpc_con_concurrencia_reservada_de_5(plantilla):
    funciones = plantilla.find_resources("AWS::Lambda::Function")
    assert len(funciones) == 3
    handlers = set()
    for f in funciones.values():
        p = f["Properties"]
        assert p["Runtime"] == "python3.12" and p["Architectures"] == ["arm64"]
        assert p["MemorySize"] == 256 and p["Timeout"] == 10
        assert p["ReservedConcurrentExecutions"] == 5
        assert p["VpcConfig"]["SubnetIds"] and p["VpcConfig"]["SecurityGroupIds"]
        assert "CC_DB_SECRET_ARN" in p["Environment"]["Variables"]
        handlers.add(p["Handler"])
    assert handlers == {
        "cognito_triggers.pre_signup.handler",
        "cognito_triggers.post_confirmation.handler",
        "cognito_triggers.pre_token.handler",
    }


def test_lambdas_con_registros_de_30_dias(plantilla):
    grupos = plantilla.find_resources("AWS::Logs::LogGroup")
    assert len(grupos) == 3
    for g in grupos.values():
        assert g["Properties"]["RetentionInDays"] == 30


def test_en_test_sin_host_de_proxy_las_lambdas_usan_el_host_del_secreto(plantilla):
    for f in plantilla.find_resources("AWS::Lambda::Function").values():
        assert "CC_DB_HOST" not in f["Properties"]["Environment"]["Variables"]


def test_solo_post_confirmation_actualiza_atributos_del_grupo(plantilla):
    politicas = plantilla.find_resources("AWS::IAM::Policy")
    con_cognito = [
        p
        for p in politicas.values()
        if "cognito-idp:AdminUpdateUserAttributes" in json.dumps(p["Properties"]["PolicyDocument"])
    ]
    assert len(con_cognito) == 1
    (sentencia,) = (
        s
        for s in con_cognito[0]["Properties"]["PolicyDocument"]["Statement"]
        if "cognito-idp:AdminUpdateUserAttributes" in json.dumps(s)
    )
    assert sentencia["Resource"] != "*"
    assert len(con_cognito[0]["Properties"]["Roles"]) == 1
    assert "postconfirmation" in json.dumps(con_cognito[0]["Properties"]["Roles"]).lower()


def test_las_lambdas_leen_solo_el_secreto_de_svc_dashboard(plantilla):
    texto = json.dumps(plantilla.find_resources("AWS::IAM::Policy"))
    assert "secretsmanager:GetSecretValue" in texto
    for rol in ("svc_colaboradores", "svc_campos", "svc_constancias", "svc_whatsapp", "migrador"):
        assert rol not in texto


def test_sin_credenciales_en_la_plantilla(plantilla):
    assert "AKIA" not in json.dumps(plantilla.to_json())


def test_sin_el_paquete_de_lambdas_la_sintesis_falla(monkeypatch, tmp_path):
    """Desplegar sin las dependencias dejaría a todos sin poder iniciar sesión."""
    import infra.stacks.auth as auth

    monkeypatch.delenv("CC_LAMBDAS_DESDE_FUENTE")
    monkeypatch.setattr(auth, "PAQUETE", tmp_path / "inexistente")
    with pytest.raises(FileNotFoundError, match="empaquetar_lambdas"):
        auth._codigo_lambdas()


def test_cada_lambda_puede_descifrar_con_la_llave_del_secreto(plantilla):
    """Leer un secreto cifrado con KMS exige también kms:Decrypt: CDK no lo concede cuando el
    secreto es el adjunto de la instancia (falló en T-047)."""
    por_rol: dict[str, bool] = {}
    for pol in plantilla.find_resources("AWS::IAM::Policy").values():
        for s in pol["Properties"]["PolicyDocument"]["Statement"]:
            acciones = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            if "kms:Decrypt" in acciones:
                assert s["Resource"] != "*"
                for rol in pol["Properties"]["Roles"]:
                    por_rol[json.dumps(rol)] = True
    for nombre in ("presignup", "postconfirmation", "pretoken"):
        assert any(nombre in rol.lower() for rol in por_rol), nombre
