import time
import os
import multiprocessing as mp
import sys
from procfs import read_status, read_stat, read_cmdline, uid_a_usuario

# Diccionario local para guardar la lectura anterior de jiffies por PID
_anteriores = {}  # pid -> (jiffies_totales, timestamp)
_HZ = os.sysconf('SC_CLK_TCK')  # tipicamente 100

def _calcular_cpu(pid, utime, stime):
    """Calcula CPU% comparando con la lectura anterior."""
    global _anteriores
    ahora = time.time()
    jiffies = int(utime) + int(stime)

    anterior = _anteriores.get(pid)
    _anteriores[pid] = (jiffies, ahora)

    if anterior is None:
        return 0.0

    jiffies_prev, t_prev = anterior
    delta_j = jiffies - jiffies_prev
    delta_t = ahora - t_prev

    if delta_t <= 0:
        return 0.0

    return round((delta_j / _HZ) / delta_t * 100, 1)


def resumen(queue_pids, queue_datos, intervalo=2.0):
    print(f"[Resumen] Iniciado con PID {mp.current_process().pid}", file=sys.stderr)

    while True:
        try:
            lista_pids = queue_pids.get(timeout=5.0)
        except Exception:
            continue

        resultados = {}

        for info in lista_pids:
            pid = info['pid']

            status = read_status(pid)
            stat   = read_stat(pid)
            cmd    = read_cmdline(pid)

            if status is None or stat is None:
                continue

            uid_num = status.get('Uid', '0').split()[0]

            # utime campo 14, stime campo 15 (índices 13 y 14 en la lista)
            try:
                utime = stat[13]
                stime = stat[14]
                cpu_pct = _calcular_cpu(pid, utime, stime)
            except (IndexError, ValueError):
                cpu_pct = 0.0

            # VmRSS en kB
            vm_rss = status.get('VmRSS', '0 kB').replace(' kB', '').strip()

            resultados[pid] = {
                'pid':     pid,
                'ppid':    status.get('PPid', '?'),
                'usuario': uid_a_usuario(uid_num),
                'estado':  stat[2],
                'threads': status.get('Threads', '?'),
                'comando': cmd or '?',
                'cpu_pct': cpu_pct,
                'vm_rss':  vm_rss,
            }

        queue_datos.put({
            'clave': 'resumen',
            'datos': resultados
        })

        time.sleep(intervalo)