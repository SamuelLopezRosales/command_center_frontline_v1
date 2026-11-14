"""Cliente de Cognito para administrar usuarios (design.md §3.2, §11.2).

El servicio solo necesita deshabilitar un usuario y cerrar todas sus sesiones. Se define como
``Protocol`` para sustituirlo por un simulado en las pruebas. Las llamadas de boto3 son
bloqueantes, por lo que se ejecutan en un hilo.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from cc_common.errores import ErrorProveedor


class ClienteCognito(Protocol):
    async def deshabilitar_y_cerrar_sesiones(self, username: str) -> None: ...


class ClienteCognitoAws:
    """``AdminDisableUser`` y ``AdminUserGlobalSignOut`` sobre el grupo ``cc-{env}``."""

    def __init__(self, user_pool_id: str, region: str | None = None, cliente: Any | None = None):
        self._pool = user_pool_id
        if cliente is None:
            import boto3

            cliente = boto3.client("cognito-idp", region_name=region)
        self._c = cliente

    def _ejecutar(self, username: str) -> None:
        self._c.admin_disable_user(UserPoolId=self._pool, Username=username)
        self._c.admin_user_global_sign_out(UserPoolId=self._pool, Username=username)

    async def deshabilitar_y_cerrar_sesiones(self, username: str) -> None:
        try:
            await asyncio.to_thread(self._ejecutar, username)
        except Exception as exc:  # el detalle del proveedor no se expone al cliente
            raise ErrorProveedor(
                "COGNITO_NO_DISPONIBLE", "No fue posible desactivar la cuenta."
            ) from exc
