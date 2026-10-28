"""Fixtures compartidas por los tests.

Los tests usan el pool directamente, sin pasar por HTTP: así se puede
controlar el momento exacto de cada cancelación. Las descargas van contra un
servidor falso (httpx.MockTransport) para no depender de internet.
"""

import asyncio
import time
from concurrent.futures import ProcessPoolExecutor

import httpx
import pytest_asyncio

import tareas
from cola import PoolWorkers
from modelos import ESTADOS_FINALES, Estado, Tarea

# Lo que el servidor falso registra, para que los tests lo inspeccionen
servidor_falso = {"activas": 0, "max_activas": 0, "canceladas": 0}


async def responder(peticion: httpx.Request) -> httpx.Response:
    """Servidor falso: /demora/<segundos> tarda eso en responder."""
    segundos = float(peticion.url.path.rsplit("/", 1)[-1])
    servidor_falso["activas"] += 1
    servidor_falso["max_activas"] = max(servidor_falso["max_activas"],
                                        servidor_falso["activas"])
    try:
        await asyncio.sleep(segundos)
    except asyncio.CancelledError:
        servidor_falso["canceladas"] += 1
        raise
    finally:
        servidor_falso["activas"] -= 1
    return httpx.Response(200, content=b"x" * 100)


@pytest_asyncio.fixture(autouse=True)
async def recursos():
    """Lo que en producción crea el lifespan, en versión de prueba."""
    servidor_falso.update(activas=0, max_activas=0, canceladas=0)
    tareas.cliente_http = httpx.AsyncClient(
        transport=httpx.MockTransport(responder), base_url="http://falso")
    tareas.pool_cpu = ProcessPoolExecutor(max_workers=1)
    # Cada test corre en un event loop nuevo, y las primitivas de asyncio
    # quedan atadas al loop donde se usan por primera vez: hay que recrearla
    tareas.limite_descargas = asyncio.Semaphore(2)
    yield
    await tareas.cliente_http.aclose()
    # Igual que en el apagado: matar un hash que haya quedado corriendo
    for proceso in list((tareas.pool_cpu._processes or {}).values()):
        proceso.kill()
    tareas.pool_cpu.shutdown(wait=True, cancel_futures=True)


@pytest_asyncio.fixture
async def pool():
    p = PoolWorkers(cantidad=2, timeout_default=5, cola_max=5)
    p.iniciar()
    yield p
    if p._workers:
        await p.detener(limite=1)


async def esperar_estado(tarea: Tarea, estados=ESTADOS_FINALES,
                         limite: float = 5) -> float:
    """Espera (cediendo el loop) a que la tarea llegue a alguno de esos estados.

    Devuelve cuánto tardó.
    """
    if isinstance(estados, Estado):
        estados = {estados}
    inicio = time.perf_counter()
    while tarea.estado not in estados:
        if time.perf_counter() - inicio > limite:
            raise AssertionError(f"La tarea quedó en {tarea.estado.value}")
        await asyncio.sleep(0.01)
    return time.perf_counter() - inicio
