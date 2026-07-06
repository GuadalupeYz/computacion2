import multiprocessing as mp
from display import display
from analizadores.resumen import resumen
from analizadores.sistema import sistema
from recolector import recolector
from agregador import agregador

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
        for p in [p_resumen, p_sistema, p_recolector, p_agregador, p_display]:
            p.terminate()
            p.join()
        manager.shutdown()

if __name__ == '__main__':
    main()