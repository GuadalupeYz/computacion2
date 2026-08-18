import signal
import json
import os
import time


def configurar_señales(snapshot, procesos, intervalos):
    """
    Registra los handlers para las señales que recibe el monitor.
    snapshot:   Manager.dict compartido
    procesos:   lista de procesos hijo para terminarlos limpiamente
    intervalos: dict de multiprocessing.Value con los intervalos por vista
    """

    def handler_shutdown(signum, frame):
        """SIGINT y SIGTERM: apagado limpio."""
        print(f"\n[Señales] Recibida señal {signum}, apagando...")
        for p in procesos:
            p.terminate()
        for p in procesos:
            p.join()
        exit(0)

    def handler_dump(signum, frame):
        """SIGUSR1: dump del snapshot actual a JSON."""
        try:
            timestamp = int(time.time())
            nombre = f'/app/dump_{timestamp}.json'
            datos = {}
            for k in list(snapshot.keys()):
                try:
                    datos[k] = dict(snapshot[k]) if hasattr(snapshot[k], 'keys') else snapshot[k]
                except:
                    datos[k] = str(snapshot[k])
            with open(nombre, 'w') as f:
                json.dump(datos, f, indent=2, default=str)
        except Exception as e:
            try:
                with open('/app/error_dump.txt', 'w') as f:
                    f.write(str(e))
            except:
                pass

    def handler_verbose(signum, frame):
        """SIGUSR2: toggle modo verbose — el display lo lee de snapshot['verbose']."""
        actual = snapshot.get('verbose', False)
        snapshot['verbose'] = not actual

    def handler_reload(signum, frame):
        """SIGHUP: recarga config.json y actualiza los Value de intervalos."""
        try:
            with open('/app/config.json', 'r') as f:
                config = json.load(f)
            snapshot['config'] = config
            nuevos = config.get('intervalos', {})
            for vista, value in intervalos.items():
                if vista in nuevos:
                    with value.get_lock():
                        value.value = float(nuevos[vista])
        except Exception:
            pass
    
    signal.signal(signal.SIGINT,  handler_shutdown)
    signal.signal(signal.SIGTERM, handler_shutdown)
    signal.signal(signal.SIGUSR1, handler_dump)
    signal.signal(signal.SIGUSR2, handler_verbose)
    signal.signal(signal.SIGHUP,  handler_reload)