"""Implementación de cada tipo de tarea.

Cada ejecutor es una corrutina que recibe los parámetros y devuelve el
resultado. El pool no sabe nada de tipos: busca el ejecutor en EJECUTORES.

Semana 1: `esperar` ya es real; `descargar` y `hashear` devuelven datos
simulados para poder probar la API y la cola de punta a punta.
"""

import asyncio
import hashlib
from typing import Any


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
    # TODO: así como está bloquea el event loop; pasarlo a un executor
    resultado = hash_iterado(texto, iteraciones)
    return {"iteraciones": iteraciones, "hash": resultado}


EJECUTORES = {
    "esperar": esperar,
    "descargar": descargar,
    "hashear": hashear,
}
