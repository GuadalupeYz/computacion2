import multiprocessing as mp
from display import display
from analizadores.resumen import resumen
from analizadores.sistema import sistema
from recolector import recolector
from agregador import agregador
from analizadores.memoria import memoria
from analizadores.threads import threads
from analizadores.fds import fds
from analizadores.senales import senales

def main():
    manager = mp.Manager()
    snapshot = manager.dict()
    lock = manager.Lock()
    
    queue_datos = mp.Queue()
    queue_pids = mp.Queue()
    
    p_resumen    = mp.Process(target=resumen,    args=(queue_pids, queue_datos), name='resumen')
    p_sistema    = mp.Process(target=sistema,    args=(queue_datos,),            name='sistema')
    p_recolector = mp.Process(target=recolector, args=(queue_pids,),             name='recolector')
    p_agregador  = mp.Process(target=agregador,  args=(snapshot, lock, queue_datos), name='agregador')
    p_display    = mp.Process(target=display,    args=(snapshot,),               name='display')
    p_memoria    = mp.Process(target=memoria, args=(queue_pids, queue_datos), name='memoria')
    p_fds = mp.Process(target=fds, args=(queue_pids, queue_datos), name='fds')
    p_threads = mp.Process(target=threads, args=(queue_pids, queue_datos), name='threads')
    p_senales = mp.Process(target=senales, args=(queue_pids, queue_datos), name='senales')
    
    p_senales.start()
    p_threads.start()
    p_fds.start()             
    p_memoria.start()    
    p_resumen.start()
    p_sistema.start()
    p_recolector.start()
    p_agregador.start()
    p_display.start()
    
    try:
        p_display.join()  # esperamos al display, si cierra, cerramos todo
    except KeyboardInterrupt:
        print("\n[Main] Deteniendo...")
    finally:
        for p in [p_resumen, p_sistema, p_recolector, p_agregador, p_display, p_memoria, p_fds, p_threads, p_senales]:
            p.terminate()
            p.join()
        manager.shutdown()

if __name__ == '__main__':
    main()