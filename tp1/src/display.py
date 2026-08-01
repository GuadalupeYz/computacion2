import time
import threading
import os, termios, tty
import multiprocessing as mp
from rich.console import Console
from rich.table import Table
from rich.live import Live

console = Console()
vista_activa = 'resumen'


def leer_teclado():
    global vista_activa
    vistas = {
        '1': 'resumen', 'r': 'resumen',
        '2': 'memoria', 'm': 'memoria',
        '3': 'fds',     'f': 'fds',
        '4': 'threads', 't': 'threads',
        '5': 'senales', 's': 'senales',
        '6': 'scheduling', 'p': 'scheduling',
        '7': 'sistema', 'g': 'sistema',
    }
    tty_fd = os.open('/dev/tty', os.O_RDONLY)
    config_original = termios.tcgetattr(tty_fd)
    try:
        tty.setcbreak(tty_fd)  # <-- setcbreak, no setraw
        while True:
            tecla = os.read(tty_fd, 1).decode(errors='replace')
            if tecla in vistas:
                vista_activa = vistas[tecla]
            elif tecla == 'q':
                break
    finally:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, config_original)
        os.close(tty_fd)


def construir_tabla(snapshot):
    global vista_activa

    if vista_activa not in snapshot:
        return Table(title=f"Vista: {vista_activa} (sin datos aún)")

    datos = snapshot[vista_activa]

    if vista_activa == 'resumen':
        tabla = Table(title="Monitor de Procesos — Resumen")
        tabla.add_column("PID",     style="cyan",   width=8)
        tabla.add_column("PPID",    style="blue",   width=8)
        tabla.add_column("UID",     style="blue",   width=6)
        tabla.add_column("Estado",  style="green",  width=8)
        tabla.add_column("Threads", style="yellow", width=8)
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
        tabla.add_column("Métrica", style="cyan",  width=20)
        tabla.add_column("Valor",   style="green")
        tabla.add_row("CPU %",      str(datos.get('cpu_pct', '?')) + "%")
        tabla.add_row("Load 1min",  str(datos.get('loadavg', {}).get('load_1', '?')))
        tabla.add_row("Load 5min",  str(datos.get('loadavg', {}).get('load_5', '?')))
        tabla.add_row("Mem Total",  str(datos.get('mem_total', '?')) + " kB")
        tabla.add_row("Mem Free",   str(datos.get('mem_free',  '?')) + " kB")
        tabla.add_row("Mem Cached", str(datos.get('mem_cached','?')) + " kB")

    elif vista_activa == 'memoria':
        tabla = Table(title="Monitor de Procesos — Memoria")
        tabla.add_column("PID",      style="cyan",   width=8)
        tabla.add_column("Nombre",   style="white",  width=15)
        tabla.add_column("VmRSS",    style="green",  width=12)
        tabla.add_column("VmSize",   style="yellow", width=12)
        tabla.add_column("VmSwap",   style="red",    width=12)
        tabla.add_column("Heap kB",  style="blue",   width=10)
        tabla.add_column("Stack kB", style="blue",   width=10)
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
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("Total FDs", style="yellow", width=10)
        tabla.add_column("FD",        style="blue",   width=6)
        tabla.add_column("Tipo",      style="green",  width=8)
        tabla.add_column("Destino",   style="white")
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
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("TID",       style="blue",   width=8)
        tabla.add_column("Estado",    style="green",  width=8)
        tabla.add_column("Vol ctx",   style="yellow", width=10)
        tabla.add_column("NoVol ctx", style="red",    width=10)
        for pid, info in list(datos.items())[:15]:
            lista = info.get('threads', [])
            if not lista:
                tabla.add_row(str(pid), info['nombre'][:15], '-', '-', '-', '-')
                continue
            for t in lista[:2]:
                tabla.add_row(
                    str(pid),
                    info['nombre'][:15],
                    str(t['tid']),
                    str(t['estado']),
                    str(t['vol_ctx']),
                    str(t['nonvol_ctx']),
                )

    elif vista_activa == 'senales':
        tabla = Table(title="Monitor de Procesos — Señales")
        tabla.add_column("PID",        style="cyan",   width=8)
        tabla.add_column("Nombre",     style="white",  width=15)
        tabla.add_column("Bloqueadas", style="red",    width=20)
        tabla.add_column("Ignoradas",  style="yellow", width=20)
        tabla.add_column("Capturadas", style="green",  width=20)
        for pid, info in list(datos.items())[:20]:
            tabla.add_row(
                str(pid),
                info['nombre'][:15],
                ', '.join(info['bloqueadas'])[:20] or '-',
                ', '.join(info['ignoradas'])[:20]  or '-',
                ', '.join(info['capturadas'])[:20] or '-',
            )

    elif vista_activa == 'scheduling':
        tabla = Table(title="Monitor de Procesos — Scheduling")
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("Nice",      style="yellow", width=6)
        tabla.add_column("Política",  style="green",  width=10)
        tabla.add_column("CPU",       style="blue",   width=8)
        tabla.add_column("Vol ctx",   style="yellow", width=10)
        tabla.add_column("NoVol ctx", style="red",    width=10)
        for pid, info in list(datos.items())[:25]:
            tabla.add_row(
                str(pid),
                info['nombre'][:15],
                str(info['nice']),
                str(info['politica']),
                str(info['cpu_affinidad']),
                str(info['vol_ctx']),
                str(info['nonvol_ctx']),
            )

    else:
        tabla = Table(title=f"Vista: {vista_activa} (próximamente)")

    return tabla


def display(snapshot, intervalo=2.0):
    print(f"[Display] Iniciado con PID {mp.current_process().pid}")

    t_teclado = threading.Thread(target=leer_teclado, daemon=True)
    t_teclado.start()

    with Live(console=console, refresh_per_second=1) as live:
        while True:
            try:
                tabla = construir_tabla(snapshot)
                live.update(tabla)
            except Exception:
                pass
            time.sleep(intervalo)
