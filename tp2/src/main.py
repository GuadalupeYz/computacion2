"""API HTTP de la plataforma de tareas."""

import asyncio
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, status

import tareas
from cola import PoolWorkers
from modelos import ESTADOS_FINALES, Estado, TareaEntrada

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

WORKERS = int(os.environ.get("WORKERS", "4"))
TIMEOUT_DEFAULT = float(os.environ.get("TIMEOUT_DEFAULT", "30"))
COLA_MAX = int(os.environ.get("COLA_MAX", "100"))
PROCESOS = int(os.environ.get("PROCESOS", str(os.cpu_count() or 2)))

pool = PoolWorkers(cantidad=WORKERS, timeout_default=TIMEOUT_DEFAULT,
                   cola_max=COLA_MAX)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Todo se crea acá, con el event loop de uvicorn ya corriendo
    tareas.pool_cpu = ProcessPoolExecutor(max_workers=PROCESOS)
    pool.iniciar()
    yield
    await pool.detener()
    # shutdown(wait=True) bloquea: lo mando a un thread para no frenar el loop
    await asyncio.to_thread(tareas.pool_cpu.shutdown, wait=True,
                            cancel_futures=True)


app = FastAPI(title="Plataforma de tareas distribuidas", lifespan=lifespan)


@app.post("/tareas", status_code=status.HTTP_202_ACCEPTED)
async def crear_tarea(entrada: TareaEntrada):
    # Solo encola y responde: no espera a que la tarea termine
    try:
        tarea = pool.encolar(entrada.tipo, entrada.parametros, entrada.timeout)
    except asyncio.QueueFull:
        raise HTTPException(status_code=503,
                            detail="Cola llena, reintentá más tarde")
    return {"id": tarea.id, "estado": tarea.estado.value}


@app.get("/tareas")
async def listar_tareas(estado: Estado | None = None):
    return [t.a_dict() for t in pool.listar(estado)]


@app.get("/tareas/{tarea_id}")
async def obtener_tarea(tarea_id: str):
    tarea = pool.tareas.get(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea inexistente")
    return tarea.a_dict()


@app.delete("/tareas/{tarea_id}")
async def cancelar_tarea(tarea_id: str):
    tarea = pool.tareas.get(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea inexistente")
    if tarea.estado in ESTADOS_FINALES:
        raise HTTPException(status_code=409,
                            detail=f"La tarea ya está {tarea.estado.value}")
    tarea = pool.cancelar(tarea_id)
    return {"id": tarea.id, "estado": tarea.estado.value}


@app.get("/estadisticas")
async def estadisticas():
    return pool.estadisticas()


if __name__ == "__main__":
    # La guarda evita que el ProcessPoolExecutor (spawn en macOS/Windows)
    # vuelva a levantar el servidor al re-importar este módulo
    uvicorn.run(app, host="0.0.0.0", port=8000)
