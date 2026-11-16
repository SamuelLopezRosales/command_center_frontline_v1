"""Ayudantes de medición de las pruebas de carga locales (T-142)."""

import asyncio
import importlib.util
import statistics
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def p95(tiempos: list[float]) -> float:
    """Percentil 95 (método inclusivo) de una lista de tiempos en segundos."""
    return statistics.quantiles(tiempos, n=20, method="inclusive")[-1]


def registrar(metrica: str, valor: float | str, unidad: str = "", **condiciones) -> None:
    """Imprime una línea ``[T-142]`` fácil de copiar a docs/resultados-carga-local.md."""
    extra = " ".join(f"{k}={v}" for k, v in condiciones.items())
    print(f"\n[T-142] {metrica}: {valor} {unidad} {extra}".rstrip())


async def medir_secuencial(llamada: Callable[[], Awaitable[object]], n: int) -> list[float]:
    """Ejecuta ``llamada`` ``n`` veces, una tras otra, y devuelve cada duración."""
    tiempos = []
    for _ in range(n):
        t0 = time.perf_counter()
        await llamada()
        tiempos.append(time.perf_counter() - t0)
    return tiempos


async def medir_concurrente(
    llamada: Callable[[], Awaitable[object]], n: int, concurrencia: int
) -> list[float]:
    """``n`` llamadas con ``concurrencia`` en vuelo a la vez; la duración incluye la espera."""
    cupo = asyncio.Semaphore(concurrencia)
    tiempos: list[float] = []

    async def una() -> None:
        async with cupo:
            t0 = time.perf_counter()
            await llamada()
            tiempos.append(time.perf_counter() - t0)

    await asyncio.gather(*(una() for _ in range(n)))
    return tiempos


def fixtures_de(ruta_conftest: str, nombre_modulo: str):
    """Carga el ``conftest.py`` de un servicio con otro nombre para reutilizar sus fixtures."""
    spec = importlib.util.spec_from_file_location(nombre_modulo, RAIZ / ruta_conftest)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo
