
import os
import time
import sys
import multiprocessing as mp


def inferir_tipo(destino):
    """Infiere el tipo de FD según el destino del symlink."""
    if destino.startswith('/dev/pts') or destino.startswith('/dev/tty'):
        return 'tty'
    elif destino.startswith('socket:'):
        return 'socket'
    elif destino.startswith('pipe:'):
        return 'pipe'
    elif destino.startswith('/dev/'):
        return 'device'
    elif destino == '/dev/null':
        return 'null'
    elif destino.startswith('/'):
        return 'file'
    else:
        return 'otro'


def leer_fds(pid):
    """Lee los FDs abiertos de un proceso."""
    fds = []
    ruta = f'/proc/{pid}/fd'
    try:
        for fd in os.listdir(ruta):
            try:
                destino = os.readlink(f'{ruta}/{fd}')
                fds.append({
                    'fd':      fd,
                    'destino': destino,
                    'tipo':    inferir_tipo(destino),
                })
            except (FileNotFoundError, PermissionError):
                continue
    except (FileNotFoundError, PermissionError):
        pass
    return fds


def fds(queue_pids, queue_datos, intervalo=5.0):
    print(f"[FDs] Iniciado con PID {mp.current_process().pid}",file=sys.stderr)

    while True:
        try:
            lista_pids = queue_pids.get(timeout=5.0)
        except Exception:
            continue

        resultados = {}

        for info in lista_pids:
            pid = info['pid']
            lista_fds = leer_fds(pid)

            resultados[pid] = {
                'pid':     pid,
                'nombre':  info['nombre'],
                'total':   len(lista_fds),
                'fds':     lista_fds[:20],  # máximo 20 para no sobrecargar
            }

        queue_datos.put({
            'clave': 'fds',
            'datos': resultados
        })

        time.sleep(intervalo)