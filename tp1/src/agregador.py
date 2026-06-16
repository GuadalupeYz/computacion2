
import time
import multiprocessing as mp

def agregador(snapshot, lock, queue_datos, intervalo=1.0):
    """
    Proceso agregador: recibe datos de los analizadores por queue
    y los escribe en el snapshot global (Manager.dict compartido).
    """
    print(f"[Agregador] Iniciado con PID {mp.current_process().pid}")
    
    while True:
        try:
            # Esperamos datos de cualquier analizador (timeout para no bloquear forever)
            mensaje = queue_datos.get(timeout=2.0)
            
            # mensaje es un dict con 'clave' y 'datos'
            # Ejemplo: {'clave': 'resumen', 'datos': {...}}
            clave = mensaje['clave']
            datos = mensaje['datos']
            
            with lock:
                snapshot[clave] = datos
                
        except Exception:
            # queue vacía por timeout, seguimos esperando
            continue