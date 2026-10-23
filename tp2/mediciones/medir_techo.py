#!/usr/bin/env python3
"""Medición 3: el techo del pool. N tareas a la vez, con N creciente.

Para cada N encola N tareas de golpe, espera a que terminen y reporta el
tiempo total, la latencia de cada tarea (de encolada a terminada) y cuántas
rechazó la API con 503. Correrlo con los dos tipos:

    docker compose exec api python mediciones/medir_techo.py --tipo esperar
    docker compose exec api python mediciones/medir_techo.py --tipo hashear
    docker compose exec api python mediciones/medir_techo.py --tipo esperar -n 1 4 16 64 128
"""

import argparse
import statistics
import time

import httpx

ESTADOS_FINALES = {"completada", "fallida", "cancelada"}


def cuerpo(tipo: str, args: argparse.Namespace) -> dict:
    if tipo == "esperar":
        return {"tipo": "esperar", "parametros": {"segundos": args.segundos}}
    return {"tipo": "hashear",
            "parametros": {"texto": "techo", "iteraciones": args.iteraciones}}


def nivel(cliente: httpx.Client, n: int, body: dict) -> dict:
    ids, rechazadas = [], 0
    for _ in range(n):
        r = cliente.post("/tareas", json=body)
        if r.status_code == 503:
            rechazadas += 1
        else:
            r.raise_for_status()
            ids.append(r.json()["id"])

    pendientes = set(ids)
    tareas = {}
    while pendientes:
        time.sleep(0.2)
        for t in cliente.get("/tareas").json():
            if t["id"] in pendientes and t["estado"] in ESTADOS_FINALES:
                tareas[t["id"]] = t
                pendientes.discard(t["id"])

    if not tareas:
        return {"n": n, "rechazadas": rechazadas}
    latencias = [t["finalizada"] - t["creada"] for t in tareas.values()]
    total = (max(t["finalizada"] for t in tareas.values())
             - min(t["creada"] for t in tareas.values()))
    fallidas = sum(t["estado"] != "completada" for t in tareas.values())
    return {"n": n, "total": total, "prom": statistics.mean(latencias),
            "max": max(latencias), "rechazadas": rechazadas,
            "fallidas": fallidas}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--tipo", choices=["esperar", "hashear"], default="esperar")
    p.add_argument("-n", type=int, nargs="+", default=[1, 2, 4, 8, 16, 32, 64],
                   help="cantidades de tareas simultáneas a probar")
    p.add_argument("--segundos", type=float, default=1.0,
                   help="duración de cada `esperar`")
    p.add_argument("--iteraciones", type=int, default=1_000_000,
                   help="iteraciones de cada `hashear`")
    args = p.parse_args()

    body = cuerpo(args.tipo, args)
    with httpx.Client(base_url=args.api, timeout=60) as cliente:
        workers = cliente.get("/estadisticas").json()["workers"]
        print(f"Tipo: {args.tipo} | workers del pool: {workers}")
        filas = []
        for n in args.n:
            fila = nivel(cliente, n, body)
            filas.append(fila)
            if "total" in fila:
                print(f"  N={n:<4} total {fila['total']:6.2f} s | latencia "
                      f"prom {fila['prom']:6.2f} s, máx {fila['max']:6.2f} s"
                      f" | 503: {fila['rechazadas']}"
                      + (f" | no completadas: {fila['fallidas']}"
                         if fila["fallidas"] else ""))
            else:
                print(f"  N={n:<4} todas rechazadas (503: {fila['rechazadas']})")

    print()
    print("| N | Tiempo total | Latencia promedio | Latencia máxima | Rechazadas (503) |")
    print("|---|--------------|-------------------|-----------------|------------------|")
    for f in filas:
        if "total" in f:
            print(f"| {f['n']} | {f['total']:.2f} s | {f['prom']:.2f} s "
                  f"| {f['max']:.2f} s | {f['rechazadas']} |")
        else:
            print(f"| {f['n']} | - | - | - | {f['rechazadas']} |")


if __name__ == "__main__":
    main()
