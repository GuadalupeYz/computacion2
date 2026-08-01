
import time
import multiprocessing as mp
import sys
from procfs import read_status, read_stat

POLITICAS = {
    '0': 'NORMAL',
    '1': 'FIFO',
    '2': 'RR',
    '3': 'BATCH',
    '5': 'IDLE',
    '6': 'DEADLINE',
}

def scheduling(queue_pids, queue_datos, intervalo=10.0):
    print(f"[Scheduling] Iniciado con PID {mp.current_process().pid}",file=sys.stderr)

    while True:
        try:
            lista_pids = queue_pids.get(timeout=5.0)
        except Exception:
            continue

        resultados = {}

        for info in lista_pids:
            pid    = info['pid']
            status = read_status(pid)
            stat   = read_stat(pid)

            if status is None or stat is None:
                continue

            politica_num = stat[40] if len(stat) > 40 else '0'

            resultados[pid] = {
                'pid':        pid,
                'nombre':     info['nombre'],
                'nice':       stat[18]  if len(stat) > 18 else '?',
                'priority':   stat[17]  if len(stat) > 17 else '?',
                'politica':   POLITICAS.get(politica_num, politica_num),
                'rt_priority': stat[39] if len(stat) > 39 else '?',
                'cpu_affinidad': status.get('Cpus_allowed_list', '?'),
                'vol_ctx':    status.get('voluntary_ctxt_switches',    '?'),
                'nonvol_ctx': status.get('nonvoluntary_ctxt_switches', '?'),
                'utime':      stat[13]  if len(stat) > 13 else '?',
                'stime':      stat[14]  if len(stat) > 14 else '?',
                'sid':        stat[5]   if len(stat) > 5  else '?',
                'pgid':       stat[4]   if len(stat) > 4  else '?',
            }

        queue_datos.put({
            'clave': 'scheduling',
            'datos': resultados
        })

        time.sleep(intervalo)