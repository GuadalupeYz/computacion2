
import time
import multiprocessing as mp
import sys
from procfs import read_status, read_stat, read_cmdline
from procfs import uid_a_usuario 

def resumen(queue_pids, queue_datos, intervalo=2.0):
    """  Analizador de resumen: lee datos básicos de cada PID
    y los manda al agregador via queue_datos.  """
    print(f"[Resumen] Iniciado con PID {mp.current_process().pid}",file=sys.stderr)
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
            resultados[pid] = {
                'pid':     pid,
                'ppid':    status.get('PPid', '?'),
                'usuario':     uid_a_usuario(uid_num),
                'estado':  stat[2],
                'threads': status.get('Threads', '?'),
                'comando': cmd or '?',
            }
        queue_datos.put({
            'clave': 'resumen',
            'datos': resultados
        })
        time.sleep(intervalo)

        