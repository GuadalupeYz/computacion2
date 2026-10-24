"""Experimento mínimo sobre kenward.cattle (agridat, licencia MIT).

Predice el peso a +14 días a partir de la historia de pesajes del animal.
Compara dos líneas base contra una regresión lineal, con validación cruzada
agrupada por animal (ningún animal aparece en entrenamiento y prueba a la vez).
Uso: python3 -I kenward_baseline.py /ruta/a/kenward.cattle.txt
"""
import csv
import sys
from collections import defaultdict

import numpy as np

H = 14  # horizonte en días


def cargar(ruta):
    animales = defaultdict(list)
    with open(ruta) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            animales[r["animal"]].append((int(r["day"]), float(r["weight"]), r["trt"]))
    return {a: sorted(v) for a, v in animales.items()}


def ejemplos(animales):
    """Una fila por (animal, pesaje t) con al menos 3 pesajes previos y un pesaje en t+H."""
    filas = []
    for a, serie in animales.items():
        dias = [d for d, _, _ in serie]
        pesos = {d: w for d, w, _ in serie}
        for i, t in enumerate(dias):
            if i < 2 or (t + H) not in pesos:
                continue
            w_t, w_prev, w_0 = pesos[t], pesos[dias[i - 1]], pesos[dias[0]]
            adg_ult = (w_t - w_prev) / (t - dias[i - 1])
            adg_acum = (w_t - w_0) / (t - dias[0])
            filas.append(dict(animal=a, t=t, w_t=w_t, adg_ult=adg_ult,
                              adg_acum=adg_acum, trt=1.0 if serie[0][2] == "B" else 0.0,
                              y=pesos[t + H]))
    return filas


def main(ruta):
    filas = ejemplos(cargar(ruta))
    ids = sorted({f["animal"] for f in filas})
    rng = np.random.default_rng(42)
    rng.shuffle(ids)
    folds = np.array_split(ids, 5)
    err = defaultdict(list)
    for k, prueba in enumerate(folds):
        prueba = set(prueba)
        tr = [f for f in filas if f["animal"] not in prueba]
        te = [f for f in filas if f["animal"] in prueba]
        X = lambda fs: np.array([[1, f["w_t"], f["adg_ult"], f["adg_acum"], f["t"], f["trt"]] for f in fs])
        y = lambda fs: np.array([f["y"] for f in fs])
        beta, *_ = np.linalg.lstsq(X(tr), y(tr), rcond=None)
        adg_media_train = np.mean([f["adg_acum"] for f in tr])
        for f, pred_lr in zip(te, X(te) @ beta):
            err["B0 sin cambio (peso actual)"].append(f["y"] - f["w_t"])
            err["B1 ADG media del entrenamiento"].append(f["y"] - (f["w_t"] + adg_media_train * H))
            err["B2 ADG acumulada del propio animal"].append(f["y"] - (f["w_t"] + f["adg_acum"] * H))
            err["M1 regresión lineal"].append(f["y"] - pred_lr)
    print(f"filas={len(filas)} animales={len(ids)} horizonte={H} d, CV 5 folds agrupada por animal")
    for nombre, e in err.items():
        e = np.array(e)
        print(f"{nombre:38s} MAE={np.mean(np.abs(e)):6.2f} kg  RMSE={np.sqrt(np.mean(e**2)):6.2f} kg")


if __name__ == "__main__":
    main(sys.argv[1])
