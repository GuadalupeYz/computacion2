
import time
import multiprocessing as mp
from procfs import read_status, read_stat


def leer_maps(pid):
    """Lee /proc/<pid>/maps y agrupa segmentos por tipo."""
    segmentos = {'heap': 0, 'stack': 0, 'text': 0, 'data': 0, 'shared': 0}
    try:
        with open(f'/proc/{pid}/maps', 'r') as f:
            for linea in f:
                partes = linea.split()
                if len(partes) < 5:
                    continue
                permisos = partes[1]
                nombre   = partes[-1] if len(partes) >= 6 else ''
                
                # tamaño del segmento en kB
                rango = partes[0].split('-')
                inicio = int(rango[0], 16)
                fin    = int(rango[1], 16)
                tam_kb = (fin - inicio) // 1024
                
                if '[heap]' in nombre:
                    segmentos['heap'] += tam_kb
                elif '[stack]' in nombre:
                    segmentos['stack'] += tam_kb
                elif 'x' in permisos and 'p' in permisos:
                    segmentos['text'] += tam_kb
                elif nombre.endswith('.so') or '.so.' in nombre:
                    segmentos['shared'] += tam_kb
                else:
                    segmentos['data'] += tam_kb
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    return segmentos


def memoria(queue_pids, queue_datos, intervalo=3.0):
    print(f"[Memoria] Iniciado con PID {mp.current_process().pid}")

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

            resultados[pid] = {
                'pid':      pid,
                'nombre':   info['nombre'],
                'vm_size':  status.get('VmSize',  '0 kB'),
                'vm_rss':   status.get('VmRSS',   '0 kB'),
                'vm_data':  status.get('VmData',  '0 kB'),
                'vm_stk':   status.get('VmStk',   '0 kB'),
                'vm_exe':   status.get('VmExe',   '0 kB'),
                'vm_lib':   status.get('VmLib',   '0 kB'),
                'vm_hwm':   status.get('VmHWM',   '0 kB'),
                'vm_swap':  status.get('VmSwap',  '0 kB'),
                'min_flt':  stat[9]  if stat else '?',
                'maj_flt':  stat[11] if stat else '?',
                'mapas':    leer_maps(pid),
            }

        queue_datos.put({
            'clave': 'memoria',
            'datos': resultados
        })

        time.sleep(intervalo)