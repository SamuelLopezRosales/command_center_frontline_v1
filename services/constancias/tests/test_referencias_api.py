"""T-208: las tres plantillas de referencia del cliente recorren todo el flujo de la API
(borrador, validación, publicación y vista previa) con PostgreSQL y LocalStack."""

import pytest
from ayudantes_constancias import crear_colaborador, sql
from ayudantes_resolucion import definiciones_referencia
from referencia import COLABORADOR, REFERENCIAS

pytestmark = pytest.mark.docker


@pytest.fixture
def mundo(datos, campos, colaboradores):
    campos.por_empresa[datos["a"]] = definiciones_referencia()
    colaborador = crear_colaborador(datos)
    colaboradores.valores[colaborador] = dict(COLABORADOR)
    colaboradores.resumenes[colaborador] = {"organizacion": {"id": 1}}
    colaboradores.organizaciones[1] = {"id": 1, "logotipo_s3_key": None}
    colaboradores.vacios = {"CAMP-0004": 3}  # NSS: tres colaboradores sin valor
    return colaborador


@pytest.mark.parametrize("nombre", ["laboral", "guarderia", "consulado"])
async def test_la_plantilla_de_referencia_se_guarda_valida_publica_y_previsualiza(
    http, h, datos, mundo, nombre
):
    p = (
        await http.post("/api/v1/plantillas", json={"nombre": f"Constancia {nombre}"}, headers=h)
    ).json()
    r = await http.put(
        f"/api/v1/plantillas/{p['id']}/borrador", json=REFERENCIAS[nombre], headers=h
    )
    assert r.status_code == 200, r.text

    v = (await http.post(f"/api/v1/plantillas/{p['id']}/borrador/validar", headers=h)).json()
    assert v["errores"] == []  # todas las variables corregidas existen y están activas
    sensibles = {a["codigo"]: a for a in v["advertencias"]}.get("VARIABLES_SENSIBLES")
    if nombre == "guarderia":
        assert sensibles is None  # la de guardería no usa datos sensibles
    else:
        assert sensibles and {"rfc", "sueldo_mensual", "sueldo_letra"} <= set(
            sensibles["variables"]
        )
    if nombre == "laboral":
        sin_nss = [a for a in v["advertencias"] if a["codigo"] == "COLABORADORES_SIN_VALOR"]
        assert [(a["variables"], a["total"]) for a in sin_nss] == [(["nss"], 3)]

    pub = await http.post(
        f"/api/v1/plantillas/{p['id']}/publicar", json={"confirmar_sensibles": True}, headers=h
    )
    assert pub.status_code == 201 and pub.json()["numero"] == 1

    previa = (
        await http.post(
            f"/api/v1/plantillas/{p['id']}/vista-previa",
            json={"colaborador_id": mundo, "version": 1},
            headers=h,
        )
    ).json()
    assert previa["faltantes"] == [] and previa["desconocidas"] == []
    html = previa["html"]
    assert "María Fernanda Ramírez Ortiz" in html and "Empresa Ejemplo, S.A. de C.V." in html
    assert "{{" not in html and "A0000000000" in html
    assert "[Logotipo de la organización]" in html  # sin logotipo en la organización
    if nombre != "guarderia":
        assert "DIECINUEVE MIL PESOS 00/100 MN" in html and "15 de marzo de 2021" in html
    else:
        assert "9:00 am a 07:00 pm" in html
    assert sql(
        datos, "SELECT activa FROM constancias.plantilla_constancia WHERE id = %s", (p["id"],)
    ) == [(True,)]
