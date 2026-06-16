
import multiprocessing as mp
from recolector import recolector

def main():
    queue_pids = mp.Queue()
    
    # Arrancamos el recolector como proceso independiente
    p_recolector = mp.Process(
        target=recolector,
        args=(queue_pids,),
        name='recolector'
    )
    p_recolector.start()
    
    # Por ahora solo leemos lo que manda el recolector e imprimimos
    try:
        while True:
            datos = queue_pids.get()
            print(f"\n=== Snapshot: {len(datos)} procesos ===")
            for p in datos[:5]:  # mostramos solo los primeros 5
                print(f"  PID={p['pid']:6}  Estado={p['estado']}  Nombre={p['nombre']}")
    except KeyboardInterrupt:
        print("\n[Main] Deteniendo...")
        p_recolector.terminate()
        p_recolector.join()

if __name__ == '__main__':
    main()