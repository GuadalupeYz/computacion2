import multiprocessing as mp
from display import display
from analizadores.resumen import resumen
from analizadores.sistema import sistema
from analizadores.memoria import memoria
from analizadores.threads import threads
from analizadores.fds import fds
from analizadores.senales import senales
from analizadores.scheduling import scheduling
from recolector import recolector
from agregador import agregador
from seniales import configurar_señales
 
import time as _time
 
def main():
    manager = mp.Manager()
    snapshot = manager.dict()
    lock     = manager.Lock()
 
    # Una queue por analizador
    queue_pids_resumen    = mp.Queue()
    queue_pids_memoria    = mp.Queue()
    queue_pids_fds        = mp.Queue()
    queue_pids_threads    = mp.Queue()
    queue_pids_senales    = mp.Queue()
    queue_pids_scheduling = mp.Queue()
 
    # Queue compartida para mandar datos al agregador
    queue_datos = mp.Queue()
 
    # Lista de queues para el recolector
    queues_pids = [
        queue_pids_resumen,
        queue_pids_memoria,
        queue_pids_fds,
        queue_pids_threads,
        queue_pids_senales,
        queue_pids_scheduling,
    ]
 
    # Value por vista para intervalos ajustables con +/-
    # Estos son memoria compartida real (mmap MAP_SHARED, clase 7)
    # El display escribe .value y cada analizador lo lee dentro de su loop
    intervalos = {
        'resumen':    mp.Value('d', 2.0),
        'memoria':    mp.Value('d', 3.0),
        'fds':        mp.Value('d', 5.0),
        'threads':    mp.Value('d', 2.0),
        'senales':    mp.Value('d', 10.0),
        'scheduling': mp.Value('d', 10.0),
        'sistema':    mp.Value('d', 2.0),
    }
 
    p_recolector = mp.Process(target=recolector, args=(queues_pids,),                                    name='recolector')
    p_agregador  = mp.Process(target=agregador,  args=(snapshot, lock, queue_datos),                     name='agregador')
    p_display    = mp.Process(target=display,    args=(snapshot, intervalos),                             name='display')
    p_sistema    = mp.Process(target=sistema,    args=(queue_datos, intervalos['sistema']),               name='sistema')
    p_resumen    = mp.Process(target=resumen,    args=(queue_pids_resumen, queue_datos, intervalos['resumen']),       name='resumen')
    p_memoria    = mp.Process(target=memoria,    args=(queue_pids_memoria, queue_datos, intervalos['memoria']),       name='memoria')
    p_fds        = mp.Process(target=fds,        args=(queue_pids_fds, queue_datos, intervalos['fds']),               name='fds')
    p_threads    = mp.Process(target=threads,    args=(queue_pids_threads, queue_datos, intervalos['threads']),       name='threads')
    p_senales    = mp.Process(target=senales,    args=(queue_pids_senales, queue_datos, intervalos['senales']),       name='senales')
    p_scheduling = mp.Process(target=scheduling, args=(queue_pids_scheduling, queue_datos, intervalos['scheduling']), name='scheduling')
 
    todos = [p_recolector, p_agregador, p_display, p_sistema,
             p_resumen, p_memoria, p_fds, p_threads, p_senales, p_scheduling]
 
    for p in todos:
        p.start()
 
    _time.sleep(3)
 
    configurar_señales(snapshot, todos, intervalos)
 
    try:
        while p_display.is_alive():
            _time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Main] Deteniendo...")
    finally:
        for p in todos:
            p.terminate()
            p.join()
        manager.shutdown()
 
if __name__ == '__main__':
    main()