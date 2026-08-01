
import time
import multiprocessing as mp
import sys

def leer_loadavg():
    with open('/proc/loadavg', 'r') as f:
        campos = f.read().split()
    return {
        'load_1':  float(campos[0]),
        'load_5':  float(campos[1]),
        'load_15': float(campos[2]),
        'procs_corriendo': int(campos[3].split('/')[0]),
        'procs_total':     int(campos[3].split('/')[1]),
    }


def leer_meminfo():
    resultado = {}
    with open('/proc/meminfo', 'r') as f:
        for linea in f:
            if ':' in linea:
                clave, valor = linea.split(':', 1)
                # extraemos solo el número, sin el 'kB'
                resultado[clave.strip()] = int(valor.strip().split()[0])
    return resultado


def leer_cpu_stat():
    """Lee los contadores de CPU de /proc/stat."""
    with open('/proc/stat', 'r') as f:
        for linea in f:
            if linea.startswith('cpu '):
                campos = linea.split()
                return {
                    'user':    int(campos[1]),
                    'nice':    int(campos[2]),
                    'system':  int(campos[3]),
                    'idle':    int(campos[4]),
                    'iowait':  int(campos[5]),
                }
    return {}


def calcular_cpu_pct(anterior, actual):
    """Calcula el % de CPU usado entre dos lecturas."""
    if not anterior:
        return 0.0
    
    prev_idle  = anterior['idle']
    curr_idle  = actual['idle']
    
    prev_total = sum(anterior.values())
    curr_total = sum(actual.values())
    
    diff_idle  = curr_idle  - prev_idle
    diff_total = curr_total - prev_total
    
    if diff_total == 0:
        return 0.0
    
    return round((1.0 - diff_idle / diff_total) * 100, 1)


def sistema(queue_datos, intervalo=2.0):
    print(f"[Sistema] Iniciado con PID {mp.current_process().pid}",file=sys.stderr)
    
    cpu_anterior = None
    
    while True:
        cpu_actual = leer_cpu_stat()
        cpu_pct    = calcular_cpu_pct(cpu_anterior, cpu_actual)
        cpu_anterior = cpu_actual
        
        meminfo  = leer_meminfo()
        loadavg  = leer_loadavg()
        
        datos = {
            'cpu_pct':  cpu_pct,
            'loadavg':  loadavg,
            'mem_total': meminfo.get('MemTotal', 0),
            'mem_free':  meminfo.get('MemFree', 0),
            'mem_available': meminfo.get('MemAvailable', 0),
            'mem_cached':    meminfo.get('Cached', 0),
            'swap_total':    meminfo.get('SwapTotal', 0),
            'swap_free':     meminfo.get('SwapFree', 0),
        }
        
        queue_datos.put({
            'clave': 'sistema',
            'datos': datos
        })
        
        time.sleep(intervalo)