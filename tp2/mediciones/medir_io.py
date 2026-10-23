#!/usr/bin/env python3
"""Medición 1: N descargas secuenciales contra N concurrentes.

Manda a la API dos tareas `descargar` con las mismas N URLs: una en modo
"secuencial" (un for con await) y otra en modo "concurrente" (gather).
Repite varias veces y reporta los tiempos y el speedup.

Uso, con el servidor levantado:

    docker compose exec api python mediciones/medir_io.py
    docker compose exec api python mediciones/medir_io.py --url https://httpbin.org/delay/2 -n 20
"""

import argparse
import statistics
import time

import httpx


def correr(cliente: httpx.Client, modo: str, urls: list[str]) -> dict:
    """Encola la tarea y espera a que termine. Devuelve la tarea final."""
    r = cliente.post("/tareas", json={
        "tipo": "descargar",
        "parametros": {"urls": urls, "modo": modo},
        # El secuencial tarda N veces más: que no lo corte el timeout default
        "timeout": 600,
    })
    r.raise_for_status()
    tarea_id = r.json()["id"]
    while True:
        tarea = cliente.get(f"/tareas/{tarea_id}").json()
        if tarea["estado"] not in ("pendiente", "ejecutando"):
            return tarea
        time.sleep(0.1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--url", default="https://httpbin.org/delay/1",
                   help="URL a descargar N veces")
    p.add_argument("-n", type=int, default=20, help="cantidad de descargas")
    p.add_argument("-r", "--repeticiones", type=int, default=3)
    args = p.parse_args()

    # Un parámetro distinto por URL para que ningún caché las junte
    sep = "&" if "?" in args.url else "?"
    urls = [f"{args.url}{sep}i={i}" for i in range(args.n)]
    tiempos: dict[str, list[float]] = {"secuencial": [], "concurrente": []}

    with httpx.Client(base_url=args.api, timeout=30) as cliente:
        for rep in range(1, args.repeticiones + 1):
            for modo in tiempos:
                tarea = correr(cliente, modo, urls)
                if tarea["estado"] != "completada":
                    raise SystemExit(f"La tarea {modo} quedó {tarea['estado']}:"
                                     f" {tarea['error']}")
                errores = [d for d in tarea["resultado"] if "error" in d]
                tiempos[modo].append(tarea["duracion"])
                print(f"  repetición {rep} {modo:12} {tarea['duracion']:6.2f} s"
                      + (f"  ({len(errores)} URLs con error)" if errores else ""))

    sec = statistics.mean(tiempos["secuencial"])
    con = statistics.mean(tiempos["concurrente"])
    print()
    print(f"URL: {args.url}  |  N = {args.n}  |  repeticiones = {args.repeticiones}")
    print()
    print("| Modo | Promedio | Mínimo | Máximo |")
    print("|------|----------|--------|--------|")
    for modo, ts in tiempos.items():
        print(f"| {modo} | {statistics.mean(ts):.2f} s | {min(ts):.2f} s "
              f"| {max(ts):.2f} s |")
    print()
    print(f"Speedup: {sec / con:.1f}x")


if __name__ == "__main__":
    main()
