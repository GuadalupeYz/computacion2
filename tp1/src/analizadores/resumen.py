import time
import os
import multiprocessing as mp
import sys
from procfs import read_status, read_stat, read_cmdline, uid_a_usuario

_anteriores = {}
_HZ = os.sysconf('SC_CLK_TCK')

def _calcular_cpu(pid, utime, stime):
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

def resumen(queue_pids, queue_datos, intervalo_value):
    """
    intervalo_value: multiprocessing.Value('d', 2.0)
    Se lee DENTRO del loop para que +/- del display tenga efecto.
    """
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
            try:
                utime = stat[13]
                stime = stat[14]
                cpu_pct = _calcular_cpu(pid, utime, stime)
            except (IndexError, ValueError):
                cpu_pct = 0.0
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
        # Limpiar entradas de PIDs que ya no existen para evitar fuga de memoria
        pids_actuales = {info['pid'] for info in lista_pids}
        for pid_muerto in list(_anteriores.keys()):
            if pid_muerto not in pids_actuales:
                del _anteriores[pid_muerto]
        queue_datos.put({'clave': 'resumen', 'datos': resultados})
        time.sleep(intervalo_value.value)
        