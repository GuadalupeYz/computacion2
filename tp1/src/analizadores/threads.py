
import os
import time
import sys
import multiprocessing as mp
from procfs import read_stat


def leer_threads(pid):
    """Lee los threads (LWPs) de un proceso desde /proc/<pid>/task/"""
    threads = []
    ruta = f'/proc/{pid}/task'
    try:
        for tid in os.listdir(ruta):
            try:
                # nombre del thread
                with open(f'{ruta}/{tid}/comm', 'r') as f:
                    nombre = f.read().strip()

                # estado y tiempos del thread
                stat = read_stat(int(tid))
                if stat is None:
                    continue

                # context switches del thread
                voluntario    = '?'
                no_voluntario = '?'
                try:
                    with open(f'{ruta}/{tid}/status', 'r') as f:
                        for linea in f:
                            if linea.startswith('voluntary_ctxt_switches'):
                                voluntario = linea.split(':')[1].strip()
                            elif linea.startswith('nonvoluntary_ctxt_switches'):
                                no_voluntario = linea.split(':')[1].strip()
                except (FileNotFoundError, PermissionError):
                    pass

                threads.append({
                    'tid':           tid,
                    'nombre':        nombre,
                    'estado':        stat[2],
                    'utime':         stat[13],
                    'stime':         stat[14],
                    'vol_ctx':       voluntario,
                    'nonvol_ctx':    no_voluntario,
                })
            except (FileNotFoundError, PermissionError):
                continue
    except (FileNotFoundError, PermissionError):
        pass
    return threads


def threads(queue_pids, queue_datos, intervalo=2.0):
    print(f"[Threads] Iniciado con PID {mp.current_process().pid}",file=sys.stderr)

    while True:
        try:
            lista_pids = queue_pids.get(timeout=5.0)
        except Exception:
            continue

        resultados = {}

        for info in lista_pids:
            pid = info['pid']
            lista_threads = leer_threads(pid)

            resultados[pid] = {
                'pid':     pid,
                'nombre':  info['nombre'],
                'total':   len(lista_threads),
                'threads': lista_threads,
            }

        queue_datos.put({
            'clave': 'threads',
            'datos': resultados
        })

        time.sleep(intervalo)