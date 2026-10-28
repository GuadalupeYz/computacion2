"""Cancelación, timeouts y apagado: que no queden tareas ni recursos colgados."""

import asyncio
import time

import pytest

import tareas
from cola import Apagando
from conftest import esperar_estado, servidor_falso
from modelos import Estado

URL = "http://falso/demora/"


def tareas_huerfanas() -> set[asyncio.Task]:
    """Tasks de ejecución que siguen vivas (se llaman tarea-<id>)."""
    return {t for t in asyncio.all_tasks()
            if t.get_name().startswith("tarea-") and not t.done()}


async def test_cancelar_pendiente_no_llega_a_ejecutarse(pool):
    # Los dos workers ocupados: la tercera queda en la cola
    ocupadas = [pool.encolar("esperar", {"segundos": 0.3}, None)
                for _ in range(2)]
    for t in ocupadas:
        await esperar_estado(t, Estado.EJECUTANDO)
    pendiente = pool.encolar("esperar", {"segundos": 0.1}, None)

    pool.cancelar(pendiente.id)
    assert pendiente.estado == Estado.CANCELADA

    for t in ocupadas:
        await esperar_estado(t)
    await asyncio.sleep(0.1)  # tiempo de sobra para que un worker la saque
    assert pendiente.iniciada is None  # el worker la descartó sin ejecutarla
    assert pool.cola.qsize() == 0


async def test_cancelar_esperar_en_ejecucion(pool):
    tarea = pool.encolar("esperar", {"segundos": 10}, None)
    await esperar_estado(tarea, Estado.EJECUTANDO)

    pool.cancelar(tarea.id)
    assert tarea.estado == Estado.CANCELADA
    assert tarea.error == "cancelada durante la ejecución"

    await asyncio.sleep(0.05)  # que el worker procese la cancelación
    assert pool.ocupados == 0
    assert not pool._en_curso
    assert not tareas_huerfanas()
    # El worker sobrevivió y toma la siguiente
    otra = pool.encolar("esperar", {"segundos": 0.05}, None)
    await esperar_estado(otra)
    assert otra.estado == Estado.COMPLETADA


async def test_cancelar_descarga_a_mitad_libera_todo(pool):
    tarea = pool.encolar("descargar", {"urls": [URL + "10", URL + "10"]}, None)
    await esperar_estado(tarea, Estado.EJECUTANDO)
    while servidor_falso["activas"] < 2:   # las dos descargas en vuelo
        await asyncio.sleep(0.01)

    pool.cancelar(tarea.id)
    await asyncio.sleep(0.05)

    assert tarea.estado == Estado.CANCELADA
    # gather canceló las dos descargas hijas: no quedó ninguna en vuelo
    assert servidor_falso["canceladas"] == 2
    assert servidor_falso["activas"] == 0
    assert not tareas_huerfanas()
    # El semáforo (de 2) quedó libre: se puede tomar dos veces sin esperar
    for _ in range(2):
        await asyncio.wait_for(tareas.limite_descargas.acquire(), timeout=0.1)


async def test_cancelar_hash_libera_al_worker_aunque_el_proceso_siga(pool):
    tarea = pool.encolar("hashear", {"texto": "x", "iteraciones": 50_000_000},
                         None)
    await esperar_estado(tarea, Estado.EJECUTANDO)
    inicio = time.perf_counter()
    pool.cancelar(tarea.id)
    await asyncio.sleep(0.05)
    assert tarea.estado == Estado.CANCELADA
    assert time.perf_counter() - inicio < 0.2  # no esperó al hash
    assert pool.ocupados == 0
    # El proceso hijo sigue calculando (la limitación conocida): el
    # fixture lo mata al terminar el test, como hace el apagado


async def test_timeout_corta_la_tarea_y_la_marca_fallida(pool):
    tarea = pool.encolar("descargar", {"urls": [URL + "10"]}, 0.3)
    espera = await esperar_estado(tarea)
    assert tarea.estado == Estado.FALLIDA
    assert tarea.error == "timeout: superó 0.3 s"
    assert espera < 1
    await asyncio.sleep(0.05)
    assert servidor_falso["canceladas"] == 1  # el timeout también cancela


async def test_cancelar_una_tarea_terminada_no_la_cambia(pool):
    tarea = pool.encolar("esperar", {"segundos": 0}, None)
    await esperar_estado(tarea)
    pool.cancelar(tarea.id)
    assert tarea.estado == Estado.COMPLETADA


async def test_cancelar_inexistente_lanza_keyerror(pool):
    with pytest.raises(KeyError):
        pool.cancelar("no-existe")


async def test_apagado_deja_terminar_y_corta_lo_que_se_pasa(pool):
    corta = pool.encolar("esperar", {"segundos": 0.2}, None)
    larga = pool.encolar("esperar", {"segundos": 10}, None)
    await esperar_estado(larga, Estado.EJECUTANDO)
    pendiente = pool.encolar("esperar", {"segundos": 0.1}, None)

    inicio = time.perf_counter()
    forzado = await pool.detener(limite=1)
    duracion = time.perf_counter() - inicio

    assert forzado is True
    assert 1 <= duracion < 1.5
    assert corta.estado == Estado.COMPLETADA     # llegó a terminar
    assert larga.estado == Estado.CANCELADA      # se le venció el límite
    assert larga.error == "cancelada por apagado"
    assert pendiente.estado == Estado.CANCELADA  # nunca se ejecutó
    assert pendiente.iniciada is None
    assert not pool._workers and not tareas_huerfanas()


async def test_apagado_sin_nada_colgado_no_fuerza(pool):
    tarea = pool.encolar("esperar", {"segundos": 0.1}, None)
    await esperar_estado(tarea, Estado.EJECUTANDO)  # si sigue pendiente, se cancela
    assert await pool.detener(limite=2) is False
    assert tarea.estado == Estado.COMPLETADA


async def test_despues_de_apagar_no_acepta_tareas(pool):
    await pool.detener(limite=1)
    with pytest.raises(Apagando):
        pool.encolar("esperar", {"segundos": 0.1}, None)


async def test_worker_cancelado_relanza_y_termina(pool):
    # Sin centinelas de por medio: si el worker se tragara su propio
    # CancelledError, volvería a esperar en la cola y no terminaría nunca
    tarea = pool.encolar("esperar", {"segundos": 10}, None)
    await esperar_estado(tarea, Estado.EJECUTANDO)
    for w in pool._workers:
        w.cancel()
    _, colgados = await asyncio.wait(pool._workers, timeout=0.5)
    assert not colgados
    assert tarea.estado == Estado.CANCELADA
    assert tarea.error == "cancelada por apagado"
    pool._workers.clear()  # ya terminaron: que el fixture no los detenga
