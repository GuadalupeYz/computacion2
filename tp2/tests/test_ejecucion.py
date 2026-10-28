"""Ejecución normal: resultados, concurrencia, errores y que el loop no se bloquee."""

import asyncio
import hashlib
import logging
import time

import pytest

import tareas
from cola import PoolWorkers
from conftest import esperar_estado, servidor_falso
from modelos import Estado

URL = "http://falso/demora/"


async def test_esperar_completa(pool):
    tarea = pool.encolar("esperar", {"segundos": 0.1}, None)
    assert tarea.estado == Estado.PENDIENTE  # encolar no espera la ejecución
    await esperar_estado(tarea)
    assert tarea.estado == Estado.COMPLETADA
    assert tarea.resultado == {"durmio": 0.1}


async def test_hashear_da_el_hash_correcto(pool):
    tarea = pool.encolar("hashear", {"texto": "hola", "iteraciones": 3}, None)
    await esperar_estado(tarea)
    esperado = b"hola"
    for _ in range(3):
        esperado = hashlib.sha256(esperado).digest()
    assert tarea.resultado["hash"] == esperado.hex()


async def test_descargar_concurrente_tarda_lo_que_la_mas_lenta(pool):
    tareas.limite_descargas = asyncio.Semaphore(10)
    urls = [URL + "0.3"] * 5
    concurrente = pool.encolar("descargar", {"urls": urls}, None)
    secuencial = pool.encolar("descargar",
                              {"urls": urls, "modo": "secuencial"}, None)
    await esperar_estado(concurrente)
    await esperar_estado(secuencial)
    assert concurrente.duracion() < 0.6          # ~0.3 s: la más lenta
    assert secuencial.duracion() >= 1.5          # ~1.5 s: la suma
    assert all(r["estado"] == 200 for r in concurrente.resultado)


async def test_semaforo_limita_las_descargas_simultaneas(pool):
    # El fixture deja el semáforo en 2
    tarea = pool.encolar("descargar", {"urls": [URL + "0.2"] * 6}, None)
    await esperar_estado(tarea)
    assert servidor_falso["max_activas"] == 2
    assert tarea.duracion() >= 0.6               # tres tandas de dos


async def test_una_url_rota_no_tira_abajo_las_demas(pool):
    urls = [URL + "0.1", "http://falso/rota/no-es-un-numero", "sin-protocolo"]
    tarea = pool.encolar("descargar", {"urls": urls}, None)
    await esperar_estado(tarea)
    assert tarea.estado == Estado.COMPLETADA
    buena, rota, invalida = tarea.resultado
    assert buena["estado"] == 200
    assert "error" in rota and "error" in invalida


@pytest.mark.parametrize("tipo, parametros", [
    ("hashear", {"iteraciones": 0}),
    ("descargar", {"urls": []}),
    ("descargar", {"urls": [URL + "0.1"], "modo": "rapido"}),
])
async def test_parametros_invalidos_dejan_la_tarea_fallida(pool, tipo, parametros):
    tarea = pool.encolar(tipo, parametros, None)
    await esperar_estado(tarea)
    assert tarea.estado == Estado.FALLIDA
    assert tarea.error.startswith("ValueError")


async def test_cola_llena_rechaza_sin_registrar_la_tarea():
    p = PoolWorkers(cantidad=1, timeout_default=5, cola_max=2)
    p.iniciar()
    try:
        corriendo = p.encolar("esperar", {"segundos": 5}, None)
        await esperar_estado(corriendo, Estado.EJECUTANDO)
        p.encolar("esperar", {"segundos": 5}, None)
        p.encolar("esperar", {"segundos": 5}, None)
        with pytest.raises(asyncio.QueueFull):
            p.encolar("esperar", {"segundos": 5}, None)
        assert len(p.tareas) == 3   # la rechazada no quedó registrada
    finally:
        await p.detener(limite=0.5)


async def test_excepcion_en_la_tarea_la_marca_fallida(pool, monkeypatch):
    async def explota(parametros):
        raise RuntimeError("algo salió mal")

    monkeypatch.setitem(tareas.EJECUTORES, "esperar", explota)
    tarea = pool.encolar("esperar", {}, None)
    await esperar_estado(tarea)
    assert tarea.estado == Estado.FALLIDA
    assert tarea.error == "RuntimeError: algo salió mal"
    # El worker sigue vivo para la próxima
    otra = pool.encolar("hashear", {"iteraciones": 1}, None)
    await esperar_estado(otra)
    assert otra.estado == Estado.COMPLETADA


async def test_error_inesperado_no_mata_al_worker(pool, caplog):
    # Un id que no existe hace fallar al worker fuera de la tarea (KeyError)
    with caplog.at_level(logging.ERROR, logger="cola"):
        pool.cola.put_nowait("id-que-no-existe")
        await asyncio.sleep(0.05)
    assert "Error inesperado" in caplog.text
    assert all(not w.done() for w in pool._workers)
    tarea = pool.encolar("esperar", {"segundos": 0.05}, None)
    await esperar_estado(tarea)
    assert tarea.estado == Estado.COMPLETADA


async def peor_atraso_durante(tarea) -> float:
    """Mide cuánto se atrasa una corrutina que quiere despertarse cada 10 ms."""
    peor = 0.0
    while tarea.estado in (Estado.PENDIENTE, Estado.EJECUTANDO):
        antes = time.perf_counter()
        await asyncio.sleep(0.01)
        peor = max(peor, time.perf_counter() - antes - 0.01)
    return peor


async def test_hashear_con_executor_no_bloquea_el_loop(pool):
    tarea = pool.encolar("hashear", {"texto": "x", "iteraciones": 2_000_000}, None)
    atraso = await peor_atraso_durante(tarea)
    assert tarea.estado == Estado.COMPLETADA
    assert atraso < 0.1


async def test_hashear_sin_executor_bloquea_el_loop(pool, monkeypatch):
    # La versión "mala" de la medición 2, para comparar
    monkeypatch.setattr(tareas, "SIN_EXECUTOR", True)
    tarea = pool.encolar("hashear", {"texto": "x", "iteraciones": 2_000_000}, None)
    atraso = await peor_atraso_durante(tarea)
    assert tarea.estado == Estado.COMPLETADA
    assert atraso > 0.3
