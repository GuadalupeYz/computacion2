"""Cola de tareas y pool de workers.

Patrón productor-consumidor: la API produce (encolar) y N corrutinas
workers consumen de una asyncio.Queue compartida. Todo corre en el mismo
hilo del event loop, así que entre dos `await` nadie más toca el estado:
por eso no hace falta Lock para el diccionario de tareas ni el contador.
"""

import asyncio
import logging
import time
from typing import Any

from modelos import ESTADOS_FINALES, Estado, Tarea
from tareas import EJECUTORES

log = logging.getLogger("cola")


class PoolWorkers:
    def __init__(self, cantidad: int, timeout_default: float,
                 cola_max: int):
        self.cantidad = cantidad
        self.timeout_default = timeout_default
        # maxsize es backpressure: la cola no puede crecer sin límite
        self.cola: asyncio.Queue[str] = asyncio.Queue(maxsize=cola_max)
        self.tareas: dict[str, Tarea] = {}
        self.ocupados = 0
        self._workers: list[asyncio.Task] = []

    def iniciar(self) -> None:
        for n in range(self.cantidad):
            self._workers.append(
                asyncio.create_task(self._worker(n), name=f"worker-{n}"))
        log.info("Pool iniciado con %d workers", self.cantidad)

    async def detener(self) -> None:
        # TODO semana 2: apagado ordenado (esperar en curso + volcado JSON)
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        log.info("Pool detenido")

    def encolar(self, tipo: str, parametros: dict[str, Any],
                timeout: float | None) -> Tarea:
        """Encola una tarea. Lanza asyncio.QueueFull si la cola está llena."""
        tarea = Tarea(tipo=tipo, parametros=parametros,
                      timeout=timeout or self.timeout_default)
        # put_nowait en vez de await put(): si está llena, falla al instante
        # en lugar de dejar al cliente HTTP esperando un lugar
        self.cola.put_nowait(tarea.id)
        # Recién se registra si entró, así no quedan tareas fantasma
        self.tareas[tarea.id] = tarea
        return tarea

    def cancelar(self, tarea_id: str) -> Tarea:
        """Cancela una tarea. Lanza KeyError si no existe."""
        tarea = self.tareas[tarea_id]
        if tarea.estado == Estado.PENDIENTE:
            # Sigue en la cola: el worker la va a descartar al sacarla
            tarea.estado = Estado.CANCELADA
            tarea.finalizada = time.time()
        # TODO semana 2: cancelar también las que están EJECUTANDO
        return tarea

    async def _worker(self, n: int) -> None:
        while True:
            tarea_id = await self.cola.get()
            try:
                tarea = self.tareas[tarea_id]
                if tarea.estado != Estado.PENDIENTE:
                    continue  # la cancelaron mientras esperaba en la cola
                await self._ejecutar(tarea, n)
            except Exception:
                # Un error inesperado no puede matar al worker
                log.exception("Error inesperado en worker-%d", n)
            finally:
                self.cola.task_done()

    async def _ejecutar(self, tarea: Tarea, n: int) -> None:
        tarea.estado = Estado.EJECUTANDO
        tarea.iniciada = time.time()
        self.ocupados += 1
        log.info("worker-%d ejecuta %s (%s)", n, tarea.id, tarea.tipo)
        try:
            ejecutor = EJECUTORES[tarea.tipo]
            tarea.resultado = await asyncio.wait_for(
                ejecutor(tarea.parametros), timeout=tarea.timeout)
            tarea.estado = Estado.COMPLETADA
        except TimeoutError:
            tarea.estado = Estado.FALLIDA
            tarea.error = f"timeout: superó {tarea.timeout} s"
        except Exception as e:
            tarea.estado = Estado.FALLIDA
            tarea.error = f"{type(e).__name__}: {e}"
        finally:
            tarea.finalizada = time.time()
            self.ocupados -= 1
            log.info("%s terminó: %s", tarea.id, tarea.estado.value)

    def listar(self, estado: Estado | None = None) -> list[Tarea]:
        return [t for t in self.tareas.values()
                if estado is None or t.estado == estado]

    def estadisticas(self) -> dict[str, Any]:
        por_estado = {e.value: 0 for e in Estado}
        duraciones = []
        for t in self.tareas.values():
            por_estado[t.estado.value] += 1
            if t.estado in ESTADOS_FINALES and t.duracion() is not None:
                duraciones.append(t.duracion())
        promedio = sum(duraciones) / len(duraciones) if duraciones else None
        return {
            "total": len(self.tareas),
            "por_estado": por_estado,
            "duracion_promedio": promedio,
            "workers": self.cantidad,
            "workers_ocupados": self.ocupados,
            "en_cola": self.cola.qsize(),
        }
