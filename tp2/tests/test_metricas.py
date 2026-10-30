"""El texto de /metrics: formato de Prometheus y valores coherentes."""

import asyncio

import pytest

import metricas
from cola import PoolWorkers
from conftest import esperar_estado


def valores(texto: str) -> dict[str, float]:
    """Lee las líneas de valores (`nombre{etiquetas} número`) a un diccionario."""
    resultado = {}
    for linea in texto.splitlines():
        if linea and not linea.startswith("#"):
            nombre, numero = linea.rsplit(" ", 1)
            resultado[nombre] = float(numero)
    return resultado


async def test_formato_cada_metrica_tiene_help_y_type(pool):
    texto = metricas.formatear(pool)
    assert texto.endswith("\n")
    lineas = texto.splitlines()
    tipos = [l for l in lineas if l.startswith("# TYPE ")]
    ayudas = [l for l in lineas if l.startswith("# HELP ")]
    assert len(tipos) == len(ayudas) == 8
    for linea in lineas:
        if not linea.startswith("#"):
            float(linea.rsplit(" ", 1)[1])  # cada valor es un número


async def test_valores_coherentes_con_el_pool(pool):
    hecha = pool.encolar("esperar", {"segundos": 0}, None)
    await esperar_estado(hecha)
    for _ in range(2):
        pool.encolar("esperar", {"segundos": 5}, None)  # ocupan los 2 workers
    await asyncio.sleep(0.05)
    pool.encolar("esperar", {"segundos": 5}, None)       # queda en la cola

    v = valores(metricas.formatear(pool))
    assert v["tareas_creadas_total"] == 4
    assert v['tareas{tipo="esperar",estado="completada"}'] == 1
    assert v['tareas{tipo="esperar",estado="ejecutando"}'] == 2
    assert v['tareas{tipo="esperar",estado="pendiente"}'] == 1
    assert v['tareas{tipo="hashear",estado="pendiente"}'] == 0  # todas las combinaciones
    assert v['tarea_duracion_segundos_count{tipo="esperar"}'] == 1
    assert v["workers"] == 2
    assert v["workers_ocupados"] == 2
    assert v["cola_en_espera"] == 1
    assert v["cola_capacidad"] == 5


async def test_rechazos_se_cuentan():
    p = PoolWorkers(cantidad=1, timeout_default=5, cola_max=1)
    p.iniciar()
    try:
        p.encolar("esperar", {"segundos": 5}, None)
        await asyncio.sleep(0.05)                    # el worker la toma
        p.encolar("esperar", {"segundos": 5}, None)  # llena la cola
        for _ in range(3):
            with pytest.raises(asyncio.QueueFull):
                p.encolar("esperar", {"segundos": 5}, None)
        v = valores(metricas.formatear(p))
        assert v["tareas_rechazadas_total"] == 3
        assert v["tareas_creadas_total"] == 2
    finally:
        await p.detener(limite=0.5)
