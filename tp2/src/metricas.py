"""Métricas en el formato de texto de Prometheus, para GET /metrics.

Cada métrica lleva una línea `# HELP` (qué es), una `# TYPE` (counter si
solo crece, gauge si sube y baja, summary para tiempos) y una línea por
valor: `nombre{etiqueta="valor"} número`.
"""

from typing import get_args

from cola import PoolWorkers
from modelos import ESTADOS_FINALES, Estado, TipoTarea


def _metrica(lineas: list[str], nombre: str, tipo: str, ayuda: str,
             valores: list[tuple[dict[str, str], float]]) -> None:
    lineas.append(f"# HELP {nombre} {ayuda}")
    lineas.append(f"# TYPE {nombre} {tipo}")
    for etiquetas, valor in valores:
        if etiquetas:
            texto = ",".join(f'{k}="{v}"' for k, v in etiquetas.items())
            lineas.append(f"{nombre}{{{texto}}} {valor}")
        else:
            lineas.append(f"{nombre} {valor}")


def formatear(pool: PoolWorkers) -> str:
    """Arma el texto de /metrics.

    No tiene ningún await: recorre el diccionario de tareas de un tirón, así
    que ve un estado consistente (ninguna corrutina lo cambia en el medio).
    """
    tipos = get_args(TipoTarea)
    por_tipo_estado = {(t, e): 0 for t in tipos for e in Estado}
    suma_duracion = {t: 0.0 for t in tipos}
    terminadas = {t: 0 for t in tipos}
    for tarea in pool.tareas.values():
        por_tipo_estado[(tarea.tipo, tarea.estado)] += 1
        duracion = tarea.duracion()
        if tarea.estado in ESTADOS_FINALES and duracion is not None:
            suma_duracion[tarea.tipo] += duracion
            terminadas[tarea.tipo] += 1

    lineas: list[str] = []
    _metrica(lineas, "tareas_creadas_total", "counter",
             "Tareas aceptadas desde que arrancó el servidor.",
             [({}, len(pool.tareas))])
    _metrica(lineas, "tareas_rechazadas_total", "counter",
             "POST rechazados con 503 (cola llena o servidor apagándose).",
             [({}, pool.rechazadas)])
    _metrica(lineas, "tareas", "gauge",
             "Tareas en cada estado, por tipo.",
             [({"tipo": t, "estado": e.value}, n)
              for (t, e), n in por_tipo_estado.items()])
    # summary sin cuantiles: con _sum y _count se calcula el promedio
    lineas.append("# HELP tarea_duracion_segundos Duración de las tareas "
                  "terminadas que llegaron a ejecutarse.")
    lineas.append("# TYPE tarea_duracion_segundos summary")
    for t in tipos:
        lineas.append(f'tarea_duracion_segundos_sum{{tipo="{t}"}} '
                      f"{suma_duracion[t]}")
        lineas.append(f'tarea_duracion_segundos_count{{tipo="{t}"}} '
                      f"{terminadas[t]}")
    _metrica(lineas, "workers", "gauge", "Workers del pool.",
             [({}, pool.cantidad)])
    _metrica(lineas, "workers_ocupados", "gauge",
             "Workers ejecutando una tarea en este momento.",
             [({}, pool.ocupados)])
    _metrica(lineas, "cola_en_espera", "gauge",
             "Elementos esperando en la cola.",
             [({}, pool.cola.qsize())])
    _metrica(lineas, "cola_capacidad", "gauge",
             "Tamaño máximo de la cola (COLA_MAX).",
             [({}, pool.cola.maxsize)])
    return "\n".join(lineas) + "\n"
