"""Persistencia mínima: volcado del estado a JSON al apagar.

El estado vive en memoria. Al apagar se escribe `estado_<timestamp>.json`,
y al arrancar se informa por log si hay un volcado previo (no se recarga).
"""

import asyncio
import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger("persistencia")


def _escribir(ruta: Path, datos: dict[str, Any]) -> None:
    """Escritura bloqueante: se llama desde un thread, nunca desde el loop."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".json.tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, default=str)
    # replace() es atómico: o queda el archivo completo o no queda nada,
    # nunca un JSON a medias si el proceso muere mientras escribe
    temporal.replace(ruta)


async def volcar(directorio: Path, tareas: list[dict[str, Any]],
                 estadisticas: dict[str, Any]) -> Path:
    marca = time.strftime("%Y%m%d-%H%M%S")
    ruta = directorio / f"estado_{marca}.json"
    datos = {"volcado": marca, "estadisticas": estadisticas, "tareas": tareas}
    # Escribir un archivo es I/O bloqueante: va a un thread (clase 21)
    await asyncio.to_thread(_escribir, ruta, datos)
    log.info("Estado volcado en %s (%d tareas)", ruta, len(tareas))
    return ruta


def reportar_previo(directorio: Path) -> None:
    """Informa por log el volcado más reciente, si existe.

    Se llama al arrancar, antes de atender pedidos: que bloquee un instante
    no le hace esperar a nadie.
    """
    volcados = sorted(directorio.glob("estado_*.json"))
    if not volcados:
        log.info("No hay volcados previos en %s", directorio)
        return
    ultimo = volcados[-1]
    try:
        datos = json.loads(ultimo.read_text(encoding="utf-8"))
        conteo = Counter(t["estado"] for t in datos["tareas"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.warning("Hay un volcado previo (%s) pero no se pudo leer: %s",
                    ultimo.name, e)
        return
    resumen = ", ".join(f"{n} {estado}" for estado, n in conteo.most_common())
    log.info("Volcado previo %s: %d tareas (%s). Volcados en total: %d",
             ultimo.name, len(datos["tareas"]), resumen or "ninguna",
             len(volcados))
