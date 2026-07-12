
import time
import multiprocessing as mp
from procfs import read_status

# Mapa de número de señal a nombre
SEÑALES = {
    1: 'SIGHUP',  2: 'SIGINT',  3: 'SIGQUIT', 4: 'SIGILL',
    5: 'SIGTRAP', 6: 'SIGABRT', 7: 'SIGBUS',  8: 'SIGFPE',
    9: 'SIGKILL', 10: 'SIGUSR1', 11: 'SIGSEGV', 12: 'SIGUSR2',
    13: 'SIGPIPE', 14: 'SIGALRM', 15: 'SIGTERM', 17: 'SIGCHLD',
    18: 'SIGCONT', 19: 'SIGSTOP', 20: 'SIGTSTP', 21: 'SIGTTIN',
    22: 'SIGTTOU', 23: 'SIGURG',  24: 'SIGXCPU', 25: 'SIGXFSZ',
    26: 'SIGVTALRM', 27: 'SIGPROF', 28: 'SIGWINCH', 29: 'SIGIO',
    30: 'SIGPWR', 31: 'SIGSYS',
}

def decodificar_mascara(hex_str):
    """Convierte una máscara hex a lista de nombres de señales activas."""
    try:
        mascara = int(hex_str, 16)
    except ValueError:
        return []
    
    resultado = []
    for num, nombre in SEÑALES.items():
        if mascara & (1 << (num - 1)):
            resultado.append(nombre)
    return resultado


def senales(queue_pids, queue_datos, intervalo=10.0):
    print(f"[Señales] Iniciado con PID {mp.current_process().pid}")

    while True:
        try:
            lista_pids = queue_pids.get(timeout=5.0)
        except Exception:
            continue

        resultados = {}

        for info in lista_pids:
            pid    = info['pid']
            status = read_status(pid)

            if status is None:
                continue

            resultados[pid] = {
                'pid':    pid,
                'nombre': info['nombre'],
                'bloqueadas': decodificar_mascara(status.get('SigBlk', '0')),
                'ignoradas':  decodificar_mascara(status.get('SigIgn', '0')),
                'capturadas': decodificar_mascara(status.get('SigCgt', '0')),
                'pendientes': decodificar_mascara(status.get('SigPnd', '0')),
            }

        queue_datos.put({
            'clave': 'senales',
            'datos': resultados
        })

        time.sleep(intervalo)