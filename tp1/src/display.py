
import time
import threading
import multiprocessing as mp
import os
import termios
import tty
from rich.console import Console
from rich.table import Table
from rich.live import Live


console = Console()
vista_activa = 'resumen'


def proceso_teclado(queue_teclas):
    """Proceso separado que lee teclas en modo raw y las manda por queue."""
    fd = os.open('/dev/tty', os.O_RDONLY)
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            tecla = os.read(fd, 1).decode('utf-8', errors='ignore')
            queue_teclas.put(tecla)
            if tecla in ('q', '\x03', '\x04'):
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        os.close(fd)

def thread_teclado(queue_teclas):
    """Thread que consume teclas de la queue y actualiza vista_activa."""
    global vista_activa
    vistas = {
        '1': 'resumen', 'r': 'resumen',
        '2': 'memoria', 'm': 'memoria',
        '3': 'fds', 'f': 'fds',
        '4': 'threads', 't': 'threads',
        '7': 'sistema', 'g': 'sistema',
    }
    while True:
        try:
            tecla = queue_teclas.get(timeout=1.0)
            if tecla in vistas:
                vista_activa = vistas[tecla]
            elif tecla in ('q', '\x03', '\x04'):
                break
        except Exception:
            continue

def construir_tabla(snapshot):
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

    elif vista_activa == 'sistema':
        tabla = Table(title="Monitor de Procesos — Sistema Global")
        tabla.add_column("Métrica", style="cyan", width=20)
        tabla.add_column("Valor",   style="green")
        tabla.add_row("CPU %",      str(datos.get('cpu_pct', '?')) + "%")
        tabla.add_row("Load 1min",  str(datos.get('loadavg', {}).get('load_1', '?')))
        tabla.add_row("Load 5min",  str(datos.get('loadavg', {}).get('load_5', '?')))
        tabla.add_row("Mem Total",  str(datos.get('mem_total', '?')) + " kB")
        tabla.add_row("Mem Free",   str(datos.get('mem_free',  '?')) + " kB")
        tabla.add_row("Mem Cached", str(datos.get('mem_cached','?')) + " kB")

    elif vista_activa == 'memoria':
        tabla = Table(title="Monitor de Procesos — Memoria")
        tabla.add_column("PID",     style="cyan",   width=8)
        tabla.add_column("Nombre",  style="white",  width=15)
        tabla.add_column("VmRSS",   style="green",  width=12)
        tabla.add_column("VmSize",  style="yellow", width=12)
        tabla.add_column("VmSwap",  style="red",    width=12)
        tabla.add_column("Heap kB", style="blue",   width=10)
        tabla.add_column("Stack kB",style="blue",   width=10)

        for pid, info in list(datos.items())[:30]:
            mapas = info.get('mapas', {})
            tabla.add_row(
                str(info['pid']),
                str(info['nombre'])[:15],
                str(info['vm_rss']),
                str(info['vm_size']),
                str(info['vm_swap']),
                str(mapas.get('heap',  0)),
                str(mapas.get('stack', 0)),
            )

    elif vista_activa == 'fds':
        tabla = Table(title="Monitor de Procesos — File Descriptors")
        tabla.add_column("PID",      style="cyan",   width=8)
        tabla.add_column("Nombre",   style="white",  width=15)
        tabla.add_column("Total FDs",style="yellow", width=10)
        tabla.add_column("FD",       style="blue",   width=6)
        tabla.add_column("Tipo",     style="green",  width=8)
        tabla.add_column("Destino",  style="white")

        for pid, info in list(datos.items())[:15]:
            lista = info.get('fds', [])
            if not lista:
                tabla.add_row(str(pid), info['nombre'][:15], str(info['total']), '-', '-', '-')
                continue
            primer = lista[0]
            tabla.add_row(
                str(pid),
                info['nombre'][:15],
                str(info['total']),
                str(primer['fd']),
                str(primer['tipo']),
                str(primer['destino'])[:40],
            )
    
    elif vista_activa == 'threads':
        tabla = Table(title="Monitor de Procesos — Threads")
        tabla.add_column("PID",     style="cyan",   width=8)
        tabla.add_column("Nombre",  style="white",  width=15)
        tabla.add_column("TID",     style="blue",   width=8)
        tabla.add_column("Estado",  style="green",  width=8)
        tabla.add_column("Vol ctx", style="yellow", width=10)
        tabla.add_column("NoVol ctx",style="red",   width=10)

        for pid, info in list(datos.items())[:15]:
            lista = info.get('threads', [])
            if not lista:
               tabla.add_row(str(pid), info['nombre'][:15], '-', '-', '-', '-')
               continue
        for t in lista[:2]:  # máximo 2 threads por proceso
            tabla.add_row(
                str(pid),
                info['nombre'][:15],
                str(t['tid']),
                str(t['estado']),
                str(t['vol_ctx']),
                str(t['nonvol_ctx']),
            )

    else:
        tabla = Table(title=f"Vista: {vista_activa} (próximamente)")

    return tabla

def display(snapshot, intervalo=2.0):
    print(f"[Display] Iniciado con PID {mp.current_process().pid}")

    # Queue para pasar teclas entre proceso y thread
    queue_teclas = mp.Queue()

    # Proceso separado para leer teclado en modo raw
    p_teclado = mp.Process(target=proceso_teclado, args=(queue_teclas,), daemon=True)
    p_teclado.start()

    # Thread que consume las teclas y actualiza vista_activa
    t_teclado = threading.Thread(target=thread_teclado, args=(queue_teclas,), daemon=True)
    t_teclado.start()

    with Live(console=console, refresh_per_second=1) as live:
        while True:
            try:
                tabla = construir_tabla(snapshot)
                live.update(tabla)
            except Exception as e:
                pass
            time.sleep(intervalo)