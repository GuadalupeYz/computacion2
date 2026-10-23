#!/usr/bin/env python3
"""Medición 2: cuánto tarda GET /tareas mientras corre un hash pesado.

Encola un `hashear` grande y, mientras se ejecuta, pide GET /tareas una y
otra vez midiendo cada respuesta. Hay que correrlo dos veces, con el
servidor levantado en cada modo:

    HASH_SIN_EXECUTOR=1 docker compose up -d
    docker compose exec api python mediciones/medir_bloqueo.py --etiqueta "sin executor"

    HASH_SIN_EXECUTOR=0 docker compose up -d
    docker compose exec api python mediciones/medir_bloqueo.py --etiqueta "con executor"
"""

import argparse
import statistics
import time

import httpx


def medir_get(cliente: httpx.Client) -> tuple[float, list[dict]]:
    inicio = time.perf_counter()
    r = cliente.get("/tareas")
    return (time.perf_counter() - inicio) * 1000, r.json()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("-i", "--iteraciones", type=int, default=10_000_000,
                   help="iteraciones del hash (10M son unos 5 s)")
    p.add_argument("--etiqueta", default="", help="texto para identificar la corrida")
    args = p.parse_args()

    # Timeout largo: sin executor, un GET puede esperar todo lo que dura el hash
    with httpx.Client(base_url=args.api, timeout=120) as cliente:
        base = [medir_get(cliente)[0] for _ in range(20)]

        r = cliente.post("/tareas", json={
            "tipo": "hashear",
            "parametros": {"texto": "medicion", "iteraciones": args.iteraciones},
            "timeout": 600,
        })
        r.raise_for_status()
        tarea_id = r.json()["id"]

        # GET /tareas trae todas las tareas: con la misma respuesta sé si
        # el hash ya terminó, sin mandar otro pedido que ensucie la medición
        latencias = []
        while True:
            ms, todas = medir_get(cliente)
            tarea = next(t for t in todas if t["id"] == tarea_id)
            if tarea["estado"] not in ("pendiente", "ejecutando"):
                break
            latencias.append(ms)

    if tarea["estado"] != "completada":
        raise SystemExit(f"El hash quedó {tarea['estado']}: {tarea['error']}")
    # El GET que vio el hash terminado también esperó durante el cálculo
    latencias.append(ms)

    print(f"Corrida: {args.etiqueta or '(sin etiqueta)'}")
    print(f"Hash de {args.iteraciones:,} iteraciones: {tarea['duracion']:.2f} s")
    print(f"GET /tareas sin carga:      promedio {statistics.mean(base):.1f} ms,"
          f" máximo {max(base):.1f} ms")
    print(f"GET /tareas durante el hash: {len(latencias)} pedidos respondidos")
    print()
    print("| Corrida | Duración del hash | GET respondidos | GET promedio | Peor GET |")
    print("|---------|-------------------|-----------------|--------------|----------|")
    print(f"| {args.etiqueta} | {tarea['duracion']:.2f} s | {len(latencias)} "
          f"| {statistics.mean(latencias):.1f} ms | {max(latencias):.1f} ms |")


if __name__ == "__main__":
    main()
