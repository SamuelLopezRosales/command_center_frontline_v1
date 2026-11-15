"""Menú de constancias (design.md §7.5; CC-REQ-075).

Con una sola plantilla activa se usa sin preguntar; con varias se envía una lista interactiva. Una
lista admite 10 filas: se muestran ``plantillas_por_pagina`` (9) y, si hay más, una fila "Ver más"
(``mas:N``). Los identificadores de fila (``plantilla:ID`` y ``mas:N``) llevan todo el estado: el
menú no guarda nada en la base.
"""

from __future__ import annotations

from typing import Any

from cc_whatsapp.bot import mensajes_es as M
from cc_whatsapp.bot import solicitud, texto
from cc_whatsapp.bot.contexto import Turno
from cc_whatsapp.servicios import salida


def lista_interactiva(plantillas: list[dict[str, Any]], pagina: int, por_pagina: int) -> dict:
    """Cuerpo de un mensaje interactivo de lista (Meta: título de fila hasta 24 caracteres y
    descripción hasta 72)."""
    inicio = pagina * por_pagina
    visibles = plantillas[inicio : inicio + por_pagina]
    filas = [
        {
            "id": f"plantilla:{p['id']}",
            "title": p["nombre"][:24],
            **({"description": p["descripcion"][:72]} if p.get("descripcion") else {}),
        }
        for p in visibles
    ]
    if inicio + por_pagina < len(plantillas):
        filas.append({"id": f"mas:{pagina + 1}", "title": M.VER_MAS})
    return {
        "type": "list",
        "body": {"text": M.MENU_CUERPO},
        "action": {"button": M.MENU_BOTON, "sections": [{"title": "Constancias", "rows": filas}]},
    }


async def mostrar(t: Turno, conv: dict, pagina: int = 0, *, reiniciar: bool = True) -> str:
    cfg = t.ctx.cfg
    plantillas = await t.ctx.constancias.plantillas(t.empresa_id)
    if not plantillas:
        await salida.enviar(
            t.conn, cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
            colaborador_id=conv["colaborador_id"], texto=M.SIN_PLANTILLAS,
        )  # fmt: skip
        return "SIN_PLANTILLAS"
    abierta = await solicitud.abrir(t, conv, reiniciar=reiniciar)
    if abierta is None:
        return "SOLICITUD_EN_PROCESO"
    if len(plantillas) == 1:
        return await solicitud.elegir(t, abierta, int(plantillas[0]["id"]))
    await salida.enviar(
        t.conn, cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
        colaborador_id=conv["colaborador_id"],
        interactivo=lista_interactiva(plantillas, pagina, cfg.plantillas_por_pagina),
    )  # fmt: skip
    return "MENU_ENVIADO"


async def atender(t: Turno, conv: dict) -> str:
    """Mensaje de una conversación ``ACTIVA`` y verificada."""
    opcion = t.msg.interactivo_id or ""
    if opcion.startswith("plantilla:") and opcion[10:].isdigit():
        return await solicitud.elegir(t, conv, int(opcion[10:]))
    if opcion.startswith("mas:") and opcion[4:].isdigit():
        return await mostrar(t, conv, int(opcion[4:]), reiniciar=False)
    if texto.es_palabra_clave(t.msg.texto):
        return await mostrar(t, conv)
    await salida.enviar(
        t.conn, t.ctx.cfg, wa_id=t.msg.wa_id, conversacion_id=conv["id"],
        colaborador_id=conv["colaborador_id"], texto=M.AYUDA,
    )  # fmt: skip
    return "AYUDA"
