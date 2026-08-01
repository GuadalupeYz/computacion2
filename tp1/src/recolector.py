import time
import multiprocessing as mp
import sys
from procfs import get_pids, read_status, read_stat

def recolector(queues_pids, intervalo=2.0):
    print(f"[Recolector] Iniciado con PID {mp.current_process().pid}", file=sys.stderr)
    
    while True:
        pids_info = []
        
        for pid in get_pids():
            stat   = read_stat(pid)
            status = read_status(pid)
            
            if stat is None or status is None:
                continue
            
            pids_info.append({
                'pid':    pid,
                'nombre': stat[1],
                'estado': stat[2],
                'ppid':   status.get('PPid', '?'),
            })
        
        for q in queues_pids:
            q.put(pids_info)
        
        time.sleep(intervalo)