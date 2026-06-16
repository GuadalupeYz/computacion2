
import time
import multiprocessing as mp
from procfs import get_pids, read_status, read_stat

def recolector(queue_pids, intervalo=2.0):
    """
    Proceso recolector: cada `intervalo` segundos lista los PIDs
    activos y pone un snapshot básico en la queue para los analizadores.
    """
    print(f"[Recolector] Iniciado con PID {mp.current_process().pid}")
    
    while True:
        pids_info = []
        
        for pid in get_pids():
            stat = read_stat(pid)
            status = read_status(pid)
            
            if stat is None or status is None:
                continue  # el proceso desapareció, lo saltamos
            
            pids_info.append({
                'pid':    pid,
                'nombre': stat[1],
                'estado': stat[2],
                'ppid':   status.get('PPid', '?'),
            })
        
        queue_pids.put(pids_info)
        time.sleep(intervalo)