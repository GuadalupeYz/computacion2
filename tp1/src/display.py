import time
import threading
import multiprocessing as mp
from rich.console import Console
from rich.table import Table
from rich.live import Live

console = Console()

# Variable compartida entre threads
vista_activa = 'resumen'


def leer_teclado():
    """Thread que escucha teclas y cambia la vista activa."""
    global vista_activa
    vistas = {
        '1': 'resumen', 'r': 'resumen',
        '2': 'memoria', 'm': 'memoria',
        '7': 'sistema', 'g': 'sistema',
    }
    with open('/dev/tty') as tty:
        while True:
            tecla = tty.read(1)
            if tecla in vistas:
                vista_activa = vistas[tecla]
            elif tecla == 'q':
                break


def construir_tabla(snapshot):
    """Construye la tabla rich según la vista activa."""
    global vista_activa

    if vista_activa not in snapshot:
        tabla = Table(title=f"Vista: {vista_activa} (sin datos aún)")
        return tabla

    datos = snapshot[vista_activa]

    if vista_activa == 'resumen':
        tabla = Table(title="Monitor de Procesos — Resumen")
        tabla.add_column("PID",     style="cyan",  width=8)
        tabla.add_column("PPID",    style="blue",  width=8)
        tabla.add_column("UID",     style="blue",  width=6)
        tabla.add_column("Estado",  style="green", width=8)
        tabla.add_column("Threads", style="yellow",width=8)
        tabla.add_column("Comando", style="white")

        for pid, info in list(datos.items())[:30]:
            tabla.add_row(
                str(info['pid']),
                str(info['ppid']),
                str(info['uid']),
                str(info['estado']),
                str(info['threads']),
                str(info['comando'])[:50],
            )
    else:
        tabla = Table(title=f"Vista: {vista_activa} (próximamente)")

    return tabla


def display(snapshot, intervalo=2.0):
    """Proceso display: muestra el snapshot en pantalla."""
    print(f"[Display] Iniciado con PID {mp.current_process().pid}")

    t_teclado = threading.Thread(target=leer_teclado, daemon=True)
    t_teclado.start()

    with Live(console=console, refresh_per_second=1) as live:
        while True:
            tabla = construir_tabla(snapshot)
            live.update(tabla)
            time.sleep(intervalo)