
import signal
import json
import os
import time

def configurar_señales(snapshot, procesos):
    """
    Registra los handlers para las señales que recibe el monitor.
    snapshot: el Manager.dict compartido
    procesos: lista de procesos hijo para terminarlos limpiamente
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
        """SIGUSR1: dump del snapshot a JSON."""
        try:
            import time, json
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
            pass

    def handler_verbose(signum, frame):
        """SIGUSR2: toggle modo verbose."""
        actual = snapshot.get('verbose', False)
        snapshot['verbose'] = not actual
        print(f"[Señales] Modo verbose: {not actual}")

    def handler_reload(signum, frame):
        """SIGHUP: recarga config desde config.json."""
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
            snapshot['config'] = config
            print("[Señales] Configuración recargada")
        except Exception as e:
            print(f"[Señales] Error al recargar config: {e}")

    signal.signal(signal.SIGINT,  handler_shutdown)
    signal.signal(signal.SIGTERM, handler_shutdown)
    signal.signal(signal.SIGUSR1, handler_dump)
    signal.signal(signal.SIGUSR2, handler_verbose)
    signal.signal(signal.SIGHUP,  handler_reload)