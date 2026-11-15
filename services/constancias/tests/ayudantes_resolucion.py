"""Definiciones de campos de la empresa de referencia (lo que devolvería INT-CAM-01)."""

from cc_constancias.clientes import DefinicionCampo, OpcionCampo


def definiciones_referencia() -> list[DefinicionCampo]:
    return [
        DefinicionCampo(1, "Área", "area", "CAMP-0001", "LISTA", orden=1),
        DefinicionCampo(
            2, "RFC del colaborador", "rfc", "CAMP-0002", "TEXTO", es_sensible=True, orden=2
        ),
        DefinicionCampo(3, "CURP", "curp", "CAMP-0003", "TEXTO", es_sensible=True, orden=3),
        DefinicionCampo(4, "NSS", "nss", "CAMP-0004", "TEXTO", es_sensible=True, orden=4),
        DefinicionCampo(
            5, "Sueldo (MXN)", "sueldo", "CAMP-0005", "NUMERO", es_sensible=True, orden=5
        ),
        DefinicionCampo(
            6,
            "Periodicidad del sueldo",
            "periodicidad_sueldo",
            "CAMP-0006",
            "LISTA",
            orden=6,
            opciones=(OpcionCampo(1, "Quincenal", "QUINCENAL"),),
        ),
        DefinicionCampo(7, "Turno", "turno", "CAMP-0007", "LISTA", orden=7),
    ]
