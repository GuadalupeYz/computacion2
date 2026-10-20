"""Implementación de cada tipo de tarea.

Cada ejecutor es una corrutina que recibe los parámetros y devuelve el
resultado. El pool no sabe nada de tipos: busca el ejecutor en EJECUTORES.

`esperar` duerme, `descargar` hace I/O de red con httpx y `hashear` calcula
en un pool de procesos.
"""

import asyncio
import hashlib
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import httpx

# Pool de procesos para lo CPU-bound. Lo crea y lo cierra el lifespan de
# main.py: crearlo por pedido costaría más que el propio cálculo.
pool_cpu: ProcessPoolExecutor | None = None

# HASH_SIN_EXECUTOR=1 calcula en el event loop: solo para la medición 2
SIN_EXECUTOR = os.environ.get("HASH_SIN_EXECUTOR") == "1"

# Cliente HTTP compartido, también creado y cerrado en el lifespan.
# Uno solo para todo: así se reutilizan las conexiones (keep-alive).
cliente_http: httpx.AsyncClient | None = None

# Tope de descargas simultáneas entre todas las tareas, para no agotar
# descriptores ni saturar a los servidores del otro lado
limite_descargas = asyncio.Semaphore(
    int(os.environ.get("DESCARGAS_MAX", "20")))


async def esperar(parametros: dict[str, Any]) -> dict[str, Any]:
    segundos = float(parametros.get("segundos", 1))
    # asyncio.sleep cede el control al event loop; time.sleep lo congelaría
    await asyncio.sleep(segundos)
    return {"durmio": segundos}


async def bajar_una(url: str) -> dict[str, Any]:
    """Descarga una URL. Si falla, devuelve el error en vez de lanzarlo."""
    async with limite_descargas:
        inicio = time.perf_counter()
        try:
            respuesta = await cliente_http.get(url)
        except Exception as e:
            # CancelledError no entra acá: hereda de BaseException
            return {"url": url, "error": f"{type(e).__name__}: {e}",
                    "segundos": time.perf_counter() - inicio}
        return {"url": url,
                "estado": respuesta.status_code,
                "bytes": len(respuesta.content),
                "segundos": time.perf_counter() - inicio}


async def descargar(parametros: dict[str, Any]) -> list[dict[str, Any]]:
    urls = parametros.get("urls")
    if not isinstance(urls, list) or not urls:
        raise ValueError("urls tiene que ser una lista no vacía")
    # Todas a la vez: tarda lo que la más lenta, no la suma
    return await asyncio.gather(*(bajar_una(str(u)) for u in urls))


def hash_iterado(texto: str, iteraciones: int) -> str:
    """Aplica SHA-256 `iteraciones` veces. Es CPU pura: no tiene ningún await."""
    datos = texto.encode()
    for _ in range(iteraciones):
        datos = hashlib.sha256(datos).digest()
    return datos.hex()


async def hashear(parametros: dict[str, Any]) -> dict[str, Any]:
    texto = str(parametros.get("texto", ""))
    iteraciones = int(parametros.get("iteraciones", 1))
    if iteraciones < 1:
        raise ValueError("iteraciones tiene que ser >= 1")
    if SIN_EXECUTOR:
        # Versión bloqueante: el loop queda congelado hasta que termine
        resultado = hash_iterado(texto, iteraciones)
    else:
        # El cálculo corre en otro proceso; esta corrutina solo espera el
        # resultado con await, y mientras tanto el loop atiende a los demás
        loop = asyncio.get_running_loop()
        resultado = await loop.run_in_executor(
            pool_cpu, hash_iterado, texto, iteraciones)
    return {"iteraciones": iteraciones, "hash": resultado}


EJECUTORES = {
    "esperar": esperar,
    "descargar": descargar,
    "hashear": hashear,
}
