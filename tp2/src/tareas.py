"""Implementación de cada tipo de tarea.

Cada ejecutor es una corrutina que recibe los parámetros y devuelve el
resultado. El pool no sabe nada de tipos: busca el ejecutor en EJECUTORES.

`esperar` y `hashear` ya son reales; `descargar` todavía devuelve datos
simulados.
"""

import asyncio
import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

# Pool de procesos para lo CPU-bound. Lo crea y lo cierra el lifespan de
# main.py: crearlo por pedido costaría más que el propio cálculo.
pool_cpu: ProcessPoolExecutor | None = None

# HASH_SIN_EXECUTOR=1 calcula en el event loop: solo para la medición 2
SIN_EXECUTOR = os.environ.get("HASH_SIN_EXECUTOR") == "1"


async def esperar(parametros: dict[str, Any]) -> dict[str, Any]:
    segundos = float(parametros.get("segundos", 1))
    # asyncio.sleep cede el control al event loop; time.sleep lo congelaría
    await asyncio.sleep(segundos)
    return {"durmio": segundos}


async def descargar(parametros: dict[str, Any]) -> list[dict[str, Any]]:
    # TODO semana 2: descargar de verdad con httpx.AsyncClient + asyncio.gather
    urls = parametros.get("urls", [])
    await asyncio.sleep(0.5)
    return [{"url": u, "estado": 200, "bytes": 0, "segundos": 0.5}
            for u in urls]


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
