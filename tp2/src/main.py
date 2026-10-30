"""API HTTP de la plataforma de tareas."""

import asyncio
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse

import persistencia
import tareas
from cola import Apagando, PoolWorkers
from modelos import ESTADOS_FINALES, Estado, TareaEntrada

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

WORKERS = int(os.environ.get("WORKERS", "4"))
TIMEOUT_DEFAULT = float(os.environ.get("TIMEOUT_DEFAULT", "30"))
COLA_MAX = int(os.environ.get("COLA_MAX", "100"))
PROCESOS = int(os.environ.get("PROCESOS", str(os.cpu_count() or 2)))
TIMEOUT_HTTP = float(os.environ.get("TIMEOUT_HTTP", "10"))
# Menor que el stop_grace_period de Docker (15 s), que después manda SIGKILL
APAGADO_MAX = float(os.environ.get("APAGADO_MAX", "10"))
ESTADO_DIR = Path(os.environ.get("ESTADO_DIR", "estados"))

pool = PoolWorkers(cantidad=WORKERS, timeout_default=TIMEOUT_DEFAULT,
                   cola_max=COLA_MAX)


@asynccontextmanager
async def lifespan(app: FastAPI):
    persistencia.reportar_previo(ESTADO_DIR)
    # Todo se crea acá, con el event loop de uvicorn ya corriendo
    tareas.pool_cpu = ProcessPoolExecutor(max_workers=PROCESOS)
    tareas.cliente_http = httpx.AsyncClient(timeout=TIMEOUT_HTTP,
                                            follow_redirects=True)
    pool.iniciar()
    yield
    # Acá llegamos cuando uvicorn recibe SIGINT/SIGTERM: ya dejó de aceptar
    # conexiones y terminó los pedidos HTTP en curso
    forzado = await pool.detener(limite=APAGADO_MAX)
    # Ya no queda nada pendiente ni corriendo: todas en estado final
    try:
        await persistencia.volcar(ESTADO_DIR,
                                  [t.a_dict() for t in pool.listar()],
                                  pool.estadisticas())
    except OSError:
        logging.exception("No se pudo volcar el estado")
    await tareas.cliente_http.aclose()
    if forzado:
        # Un hash que ya arrancó no se puede cancelar: hay que matar los
        # procesos, o shutdown(wait=True) esperaría a que terminen.
        # kill() y no terminate(): los hijos nacieron con fork y heredaron
        # el handler de SIGTERM de uvicorn, que no los hace salir. SIGKILL
        # no se puede atrapar. (_processes es interno; 3.14 trae
        # terminate_workers().)
        for proceso in list((tareas.pool_cpu._processes or {}).values()):
            proceso.kill()
    # shutdown(wait=True) bloquea: lo mando a un thread para no frenar el loop
    await asyncio.to_thread(tareas.pool_cpu.shutdown, wait=True,
                            cancel_futures=True)


app = FastAPI(title="Plataforma de tareas distribuidas", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def raiz():
    # La raíz no es parte de la API: lleva a la documentación interactiva
    return RedirectResponse("/docs")


@app.post("/tareas", status_code=status.HTTP_202_ACCEPTED)
async def crear_tarea(entrada: TareaEntrada):
    # Solo encola y responde: no espera a que la tarea termine
    try:
        tarea = pool.encolar(entrada.tipo, entrada.parametros, entrada.timeout)
    except Apagando:
        raise HTTPException(status_code=503,
                            detail="El servidor se está apagando")
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
