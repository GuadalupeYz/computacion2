
import multiprocessing as mp
from recolector import recolector
from agregador import agregador

def main():
    # Creamos el Manager (proceso servidor de memoria compartida)
    manager = mp.Manager()
    snapshot = manager.dict()
    lock = manager.Lock()
    
    # Queue para que los analizadores manden datos al agregador
    queue_datos = mp.Queue()
    
    # Queue para que el recolector mande PIDs a los analizadores
    queue_pids = mp.Queue()
    
    # Arrancamos procesos
    p_recolector = mp.Process(target=recolector, args=(queue_pids,), name='recolector')
    p_agregador = mp.Process(target=agregador, args=(snapshot, lock, queue_datos), name='agregador')
    
    p_recolector.start()
    p_agregador.start()
    
    try:
        while True:
            datos = queue_pids.get()
            print(f"\n=== Snapshot: {len(datos)} procesos ===")
            for p in datos[:5]:
                print(f"  PID={p['pid']:6}  Estado={p['estado']}  Nombre={p['nombre']}")
    except KeyboardInterrupt:
        print("\n[Main] Deteniendo...")
        p_recolector.terminate()
        p_agregador.terminate()
        p_recolector.join()
        p_agregador.join()
        manager.shutdown()

if __name__ == '__main__':
    main()