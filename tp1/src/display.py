import time
import threading
import os, termios, tty
import multiprocessing as mp
import sys
from rich.console import Console
from rich.table import Table
from rich.live import Live

console = Console()
vista_activa = 'resumen'
intervalo_actual = 2.0
mostrar_ayuda = False
orden_actual = 'pid'
indice_seleccionado = 0
proceso_pinned = None
filtro_nombre = ''
filtro_usuario = ''
en_filtro = False
ordenes = ['pid', 'nombre'] 
orden_actual = 'pid'

def leer_teclado():
    global vista_activa, intervalo_actual, mostrar_ayuda
    global ordenes, orden_actual, indice_seleccionado, proceso_pinned
    global filtro_nombre, filtro_usuario

    vistas = {
        '1': 'resumen',    'r': 'resumen',
        '2': 'memoria',    'm': 'memoria',
        '3': 'fds',        'f': 'fds',
        '4': 'threads',    't': 'threads',
        '5': 'senales',    's': 'senales',
        '6': 'scheduling', 'p': 'scheduling',
        '7': 'sistema',    'g': 'sistema',
    }
    intervalos_minimos = {
        'resumen': 0.5, 'memoria': 1.0, 'fds': 2.0,
        'threads': 0.5, 'senales': 5.0, 'scheduling': 5.0, 'sistema': 1.0
    }

    try:
        tty_fd = os.open('/dev/tty', os.O_RDONLY)
        config_original = termios.tcgetattr(tty_fd)
        tty.setcbreak(tty_fd)
        while True:
            tecla = os.read(tty_fd, 1).decode(errors='replace')

            if tecla in vistas:
                vista_activa = vistas[tecla]
                indice_seleccionado = 0
            elif tecla == '+':
                intervalo_actual = min(intervalo_actual + 0.5, 30.0)
            elif tecla == '-':
                minimo = intervalos_minimos.get(vista_activa, 0.5)
                intervalo_actual = max(intervalo_actual - 0.5, minimo)
            elif tecla in ('h', '?'):
                mostrar_ayuda = not mostrar_ayuda
            elif tecla == 'c':
                idx = ordenes.index(orden_actual)
                orden_actual = ordenes[(idx + 1) % len(ordenes)]
                indice_seleccionado = 0
            elif tecla == '/':
                 nuevo = _leer_filtro(tty_fd, 'Filtrar por nombre (Enter=aplicar, Esc=limpiar): ')
                 if nuevo == '__LIMPIAR__':
                     filtro_nombre = ''
                 else:
                     filtro_nombre = nuevo
                 indice_seleccionado = 0
            elif tecla == 'u':
                 nuevo = _leer_filtro(tty_fd, 'Filtrar por usuario (Enter=aplicar, Esc=limpiar): ')
                 if nuevo == '__LIMPIAR__':
                     filtro_usuario = ''
                 else:
                     filtro_usuario = nuevo
                 indice_seleccionado = 0
            elif tecla == '\x1b':
                b1 = os.read(tty_fd, 1).decode(errors='replace')
                b2 = os.read(tty_fd, 1).decode(errors='replace')
                if b1 == '[':
                    if b2 == 'A':
                        indice_seleccionado = max(0, indice_seleccionado - 1)
                    elif b2 == 'B':
                        indice_seleccionado += 1
            elif tecla in ('\r', '\n'):
                proceso_pinned = indice_seleccionado
            elif tecla == 'q':
                import signal
                os.kill(os.getppid(), signal.SIGTERM)
                break

    except Exception:
        pass
    finally:
        try:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, config_original)
            os.close(tty_fd)
        except:
            pass

def _leer_filtro(tty_fd, prompt):
    global en_filtro
    resultado = ''
    en_filtro = True
    try:
        fd_out = os.open('/dev/tty', os.O_WRONLY)
        # limpiamos la línea y mostramos el prompt
        os.write(fd_out, b'\r\n')
        os.write(fd_out, prompt.encode())
        while True:
            c = os.read(tty_fd, 1).decode(errors='replace')
            if c in ('\r', '\n'):
                break
            elif c == '\x1b':
                resultado = '__LIMPIAR__'
                break
            elif c in ('\x7f', '\x08'):
                if resultado:
                    resultado = resultado[:-1]
                    os.write(fd_out, b'\x08 \x08')
            else:
                resultado += c
                os.write(fd_out, c.encode())
        os.close(fd_out)
    except:
        pass
    finally:
        en_filtro = False
    return resultado

def _filtrar_items(items):
    """Aplica filtros de nombre y usuario a la lista de items."""
    resultado = items
    if filtro_nombre:
        resultado = [(pid, info) for pid, info in resultado
                     if filtro_nombre.lower() in str(info.get('nombre', '')).lower()
                     or filtro_nombre.lower() in str(info.get('comando', '')).lower()]
    if filtro_usuario:
        resultado = [(pid, info) for pid, info in resultado
                     if filtro_usuario.lower() in str(info.get('usuario', '')).lower()]
    return resultado

def _ordenar_items(items):
    if orden_actual == 'nombre':
        return sorted(items, key=lambda x: str(x[1].get('nombre', x[1].get('comando', ''))).lower())
    else:  # pid
        return sorted(items, key=lambda x: x[0])

def construir_ayuda():
    tabla = Table(title="Ayuda — Monitor de Procesos")
    tabla.add_column("Tecla",   style="cyan",  width=20)
    tabla.add_column("Acción",  style="white")
    tabla.add_row("1-7 / r,m,f,t,s,p,g", "Cambiar vista")
    tabla.add_row("↑ / ↓",     "Navegar procesos")
    tabla.add_row("Enter",      "Fijar (pin) proceso seleccionado")
    tabla.add_row("c",          "Cambiar orden (PID/RSS)")
    tabla.add_row("/",          "Filtrar por nombre")
    tabla.add_row("u",          "Filtrar por usuario")
    tabla.add_row("+",          "Aumentar intervalo de refresco")
    tabla.add_row("-",          "Disminuir intervalo de refresco")
    tabla.add_row("h / ?",      "Mostrar/ocultar esta ayuda")
    tabla.add_row("q",          "Salir limpiamente")
    return tabla

def _agregar_filas_con_navegacion(tabla, items, max_filas):
    """Agrega filas a la tabla resaltando el índice seleccionado y el pinned."""
    global indice_seleccionado, proceso_pinned

    total = len(items)
    indice_seleccionado = min(indice_seleccionado, max(0, total - 1))

    for i, (pid, info) in enumerate(items[:max_filas]):
        if i == proceso_pinned:
            estilo = "bold yellow"
        elif i == indice_seleccionado:
            estilo = "bold white on blue"
        else:
            estilo = ""
        yield i, pid, info, estilo

def construir_tabla(snapshot):
    global vista_activa, intervalo_actual, mostrar_ayuda

    if mostrar_ayuda:
        return construir_ayuda()

    if vista_activa not in snapshot:
        return Table(title=f"Vista: {vista_activa} (sin datos aún)")

    datos = snapshot[vista_activa]

    filtro_str = ""
    if filtro_nombre:
        filtro_str += f" [filtro: {filtro_nombre}]"
    if filtro_usuario:
        filtro_str += f" [usuario: {filtro_usuario}]"

    if vista_activa == 'resumen':
        tabla = Table(title=f"Monitor — Resumen [orden:{orden_actual}] [intervalo:{intervalo_actual:.1f}s]{filtro_str}")
        tabla.add_column("PID",     style="cyan",   width=8)
        tabla.add_column("PPID",    style="blue",   width=8)
        tabla.add_column("Usuario",     style="blue",   width=6)
        tabla.add_column("Estado",  style="green",  width=8)
        tabla.add_column("Threads", style="yellow", width=8)
        tabla.add_column("Comando", style="white")

        items = _filtrar_items(list(datos.items()))
        items = _ordenar_items(items)

        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 30):
            tabla.add_row(
                str(info['pid']),
                str(info['ppid']),
                str(info['usuario']),
                str(info['estado']),
                str(info['threads']),
                str(info['comando'])[:50],
                style=estilo
            )

    elif vista_activa == 'memoria':
        tabla = Table(title=f"Monitor — Memoria [orden:{orden_actual}] [intervalo:{intervalo_actual:.1f}s]{filtro_str}")
        tabla.add_column("PID",      style="cyan",   width=8)
        tabla.add_column("Nombre",   style="white",  width=15)
        tabla.add_column("VmRSS",    style="green",  width=12)
        tabla.add_column("VmSize",   style="yellow", width=12)
        tabla.add_column("VmSwap",   style="red",    width=12)
        tabla.add_column("Heap kB",  style="blue",   width=10)
        tabla.add_column("Stack kB", style="blue",   width=10)

        items = _filtrar_items(list(datos.items()))
        items = _ordenar_items(items)

        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 30):
            mapas = info.get('mapas', {})
            tabla.add_row(
                str(info['pid']),
                str(info['nombre'])[:15],
                str(info['vm_rss']),
                str(info['vm_size']),
                str(info['vm_swap']),
                str(mapas.get('heap', 0)),
                str(mapas.get('stack', 0)),
                style=estilo
            )

    elif vista_activa == 'fds':
        tabla = Table(title=f"Monitor — FDs [intervalo:{intervalo_actual:.1f}s]{filtro_str}")
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("Total FDs", style="yellow", width=10)
        tabla.add_column("FD",        style="blue",   width=6)
        tabla.add_column("Tipo",      style="green",  width=8)
        tabla.add_column("Destino",   style="white")

        items = _filtrar_items(list(datos.items()))
        items = _ordenar_items(items)

        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 15):
            lista = info.get('fds', [])
            if not lista:
                tabla.add_row(str(pid), info['nombre'][:15], str(info['total']), '-', '-', '-', style=estilo)
                continue
            primer = lista[0]
            tabla.add_row(
                str(pid),
                info['nombre'][:15],
                str(info['total']),
                str(primer['fd']),
                str(primer['tipo']),
                str(primer['destino'])[:40],
                style=estilo
            )

    elif vista_activa == 'threads':
        tabla = Table(title=f"Monitor — Threads [intervalo:{intervalo_actual:.1f}s]{filtro_str}")
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("TID",       style="blue",   width=8)
        tabla.add_column("Estado",    style="green",  width=8)
        tabla.add_column("Vol ctx",   style="yellow", width=10)
        tabla.add_column("NoVol ctx", style="red",    width=10)

        items = _filtrar_items(list(datos.items()))
        items = _ordenar_items(items)

        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 15):
            lista = info.get('threads', [])
            if not lista:
                tabla.add_row(str(pid), info['nombre'][:15], '-', '-', '-', '-', style=estilo)
                continue
            for t in lista[:2]:
                tabla.add_row(
                    str(pid),
                    info['nombre'][:15],
                    str(t['tid']),
                    str(t['estado']),
                    str(t['vol_ctx']),
                    str(t['nonvol_ctx']),
                    style=estilo
                )

    elif vista_activa == 'senales':
        tabla = Table(title=f"Monitor — Señales [intervalo:{intervalo_actual:.1f}s]{filtro_str}")
        tabla.add_column("PID",        style="cyan",   width=8)
        tabla.add_column("Nombre",     style="white",  width=15)
        tabla.add_column("Bloqueadas", style="red",    width=20)
        tabla.add_column("Ignoradas",  style="yellow", width=20)
        tabla.add_column("Capturadas", style="green",  width=20)

        items = _filtrar_items(list(datos.items()))
        items = _ordenar_items(items)

        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 20):
            tabla.add_row(
                str(pid),
                info['nombre'][:15],
                ', '.join(info['bloqueadas'])[:20] or '-',
                ', '.join(info['ignoradas'])[:20]  or '-',
                ', '.join(info['capturadas'])[:20] or '-',
                style=estilo
            )

    elif vista_activa == 'scheduling':
        tabla = Table(title=f"Monitor — Scheduling [intervalo:{intervalo_actual:.1f}s]{filtro_str}")
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("Nice",      style="yellow", width=6)
        tabla.add_column("Política",  style="green",  width=10)
        tabla.add_column("CPU",       style="blue",   width=8)
        tabla.add_column("Vol ctx",   style="yellow", width=10)
        tabla.add_column("NoVol ctx", style="red",    width=10)

        items = _filtrar_items(list(datos.items()))
        items = _ordenar_items(items)

        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 25):
            tabla.add_row(
                str(pid),
                info['nombre'][:15],
                str(info['nice']),
                str(info['politica']),
                str(info['cpu_affinidad']),
                str(info['vol_ctx']),
                str(info['nonvol_ctx']),
                style=estilo
            )

    elif vista_activa == 'sistema':
        tabla = Table(title=f"Monitor — Sistema Global [intervalo:{intervalo_actual:.1f}s]")
        tabla.add_column("Métrica", style="cyan",  width=20)
        tabla.add_column("Valor",   style="green")
        tabla.add_row("CPU %",      str(datos.get('cpu_pct', '?')) + "%")
        tabla.add_row("Load 1min",  str(datos.get('loadavg', {}).get('load_1', '?')))
        tabla.add_row("Load 5min",  str(datos.get('loadavg', {}).get('load_5', '?')))
        tabla.add_row("Mem Total",  str(datos.get('mem_total', '?')) + " kB")
        tabla.add_row("Mem Free",   str(datos.get('mem_free',  '?')) + " kB")
        tabla.add_row("Mem Cached", str(datos.get('mem_cached','?')) + " kB")

    else:
        tabla = Table(title=f"Vista: {vista_activa} (próximamente)")

    return tabla

def display(snapshot, intervalo=2.0):
    global intervalo_actual
    intervalo_actual = intervalo
    print(f"[Display] Iniciado con PID {mp.current_process().pid}", file=sys.stderr)

    t_teclado = threading.Thread(target=leer_teclado, daemon=True)
    t_teclado.start()

    # esperamos datos antes de arrancar Live
    while 'resumen' not in snapshot:
        time.sleep(0.5)

    with Live(console=console, refresh_per_second=1) as live:
        while True:
            try:
                if not en_filtro:
                    tabla = construir_tabla(snapshot)
                    live.update(tabla)
            except Exception:
                pass
            time.sleep(intervalo_actual)

