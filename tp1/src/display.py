
import time
import threading
import os, termios, tty
import multiprocessing as mp
import sys
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
 
console = Console()
vista_activa = 'resumen'
mostrar_ayuda = False
orden_actual = 'cpu'       # 'cpu', 'rss', 'pid'
indice_seleccionado = 0
proceso_pinned = None      # PID del proceso fijado (no índice)
filtro_nombre = ''
filtro_usuario = ''
en_filtro = False
ordenes = ['cpu', 'rss', 'pid']
 
# Referencias a los Value compartidos — se setean en display()
_intervalos = None
 
 
def leer_teclado():
    global vista_activa, mostrar_ayuda
    global ordenes, orden_actual, indice_seleccionado, proceso_pinned
    global filtro_nombre, filtro_usuario, _intervalos
 
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
                if _intervalos and vista_activa in _intervalos:
                    v = _intervalos[vista_activa]
                    with v.get_lock():
                        v.value = min(v.value + 0.5, 30.0)
 
            elif tecla == '-':
                if _intervalos and vista_activa in _intervalos:
                    v = _intervalos[vista_activa]
                    minimo = intervalos_minimos.get(vista_activa, 0.5)
                    with v.get_lock():
                        v.value = max(v.value - 0.5, minimo)
 
            elif tecla in ('h', '?'):
                mostrar_ayuda = not mostrar_ayuda
 
            elif tecla == 'c':
                idx = ordenes.index(orden_actual)
                orden_actual = ordenes[(idx + 1) % len(ordenes)]
                indice_seleccionado = 0
 
            elif tecla == '/':
                nuevo = _leer_filtro(tty_fd, 'Filtrar por nombre (Enter=aplicar, Esc=limpiar): ')
                filtro_nombre = '' if nuevo == '__LIMPIAR__' else nuevo
                indice_seleccionado = 0
 
            elif tecla == 'u':
                nuevo = _leer_filtro(tty_fd, 'Filtrar por usuario (Enter=aplicar, Esc=limpiar): ')
                filtro_usuario = '' if nuevo == '__LIMPIAR__' else nuevo
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
                # Pin: guardamos el PID del proceso seleccionado, no el índice
                # Así el resaltado no cambia aunque cambie el orden (consigna)
                proceso_pinned = _pid_en_indice(indice_seleccionado)
 
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
 
 
# Cache del snapshot para que leer_teclado pueda obtener el PID por índice
_ultimo_items = []
 
def _pid_en_indice(idx):
    """Devuelve el PID del proceso en la posición idx de la lista actual."""
    if 0 <= idx < len(_ultimo_items):
        pid, info = _ultimo_items[idx]
        return info.get('pid')
    return None
 
 
def _leer_filtro(tty_fd, prompt):
    global en_filtro
    resultado = ''
    en_filtro = True
    try:
        fd_out = os.open('/dev/tty', os.O_WRONLY)
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
    """Ordena por cpu%, rss o pid según orden_actual."""
    if orden_actual == 'cpu':
        return sorted(items, key=lambda x: float(x[1].get('cpu_pct', 0)), reverse=True)
    elif orden_actual == 'rss':
        def key_rss(x):
            try:
                return int(str(x[1].get('vm_rss', '0')).replace(' kB', '').strip())
            except:
                return 0
        return sorted(items, key=key_rss, reverse=True)
    else:  # pid
        return sorted(items, key=lambda x: x[0])
 
 
def construir_ayuda():
    tabla = Table(title="Ayuda — Monitor de Procesos")
    tabla.add_column("Tecla",  style="cyan",  width=20)
    tabla.add_column("Acción", style="white")
    tabla.add_row("1-7 / r,m,f,t,s,p,g", "Cambiar vista")
    tabla.add_row("↑ / ↓",    "Navegar procesos")
    tabla.add_row("Enter",     "Fijar (pin) proceso seleccionado")
    tabla.add_row("c",         "Cambiar orden (CPU% / RSS / PID)")
    tabla.add_row("/",         "Filtrar por nombre")
    tabla.add_row("u",         "Filtrar por usuario")
    tabla.add_row("+",         "Aumentar intervalo de refresco")
    tabla.add_row("-",         "Disminuir intervalo de refresco")
    tabla.add_row("h / ?",     "Mostrar/ocultar esta ayuda")
    tabla.add_row("q",         "Salir limpiamente")
    return tabla
 
 
def _agregar_filas_con_navegacion(tabla, items, max_filas):
    """Resalta por PID (proceso_pinned) y por índice (seleccionado)."""
    global indice_seleccionado, _ultimo_items
 
    total = len(items)
    indice_seleccionado = min(indice_seleccionado, max(0, total - 1))
    _ultimo_items = items  # cache para que leer_teclado pueda obtener PID
 
    for i, (pid, info) in enumerate(items[:max_filas]):
        pid_actual = info.get('pid')
        if pid_actual == proceso_pinned:
            # Pin: el proceso fijado se resalta en amarillo sin importar su posición
            estilo = "bold yellow"
        elif i == indice_seleccionado:
            estilo = "bold white on blue"
        else:
            estilo = ""
        yield i, pid, info, estilo
 
 
def _intervalo_str():
    """Devuelve el intervalo actual de la vista activa como string."""
    if _intervalos and vista_activa in _intervalos:
        return f"{_intervalos[vista_activa].value:.1f}s"
    return "?"
 
 
def construir_lista_procesos(snapshot):
    if 'resumen' not in snapshot:
        return Table(title="Procesos (cargando...)")
 
    datos = snapshot['resumen']
    items = _filtrar_items(list(datos.items()))
    items = _ordenar_items(items)
 
    # Verbose: SIGUSR2 expande cuántos procesos se muestran
    verbose = snapshot.get('verbose', False)
    max_filas = 20 if verbose else 10
 
    tabla = Table(
        title=f"Procesos [orden:{orden_actual}] [intervalo:{_intervalo_str()}]"
              + (f" [filtro:{filtro_nombre}]" if filtro_nombre else "")
              + (" [VERBOSE]" if verbose else ""),
        box=None, padding=(0, 1)
    )
    tabla.add_column("PID",     style="cyan",    width=7)
    tabla.add_column("PPID",    style="blue",    width=7)
    tabla.add_column("Usuario", style="green",   width=12)
    tabla.add_column("ST",      style="yellow",  width=4)
    tabla.add_column("CPU%",    style="red",     width=7)
    tabla.add_column("RSS kB",  style="magenta", width=9)
    tabla.add_column("TH",      style="white",   width=4)
    tabla.add_column("Comando", style="white")
 
    for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, max_filas):
        tabla.add_row(
            str(info['pid']),
            str(info['ppid']),
            str(info['usuario'])[:12],
            str(info['estado']),
            str(info.get('cpu_pct', '0.0')) + '%',
            str(info.get('vm_rss', '?')),
            str(info['threads']),
            str(info['comando'])[:35],
            style=estilo
        )
    return tabla
 
 
def construir_detalle(snapshot):
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
 
    verbose = snapshot.get('verbose', False)
    items = _filtrar_items(list(datos.items()))
    items = _ordenar_items(items)
 
    if vista_activa == 'resumen':
        tabla = Table(title=f"Detalle — Resumen [intervalo:{_intervalo_str()}]{filtro_str}")
        tabla.add_column("PID",     style="cyan",   width=8)
        tabla.add_column("PPID",    style="blue",   width=8)
        tabla.add_column("Usuario", style="blue",   width=12)
        tabla.add_column("Estado",  style="green",  width=8)
        tabla.add_column("CPU%",    style="red",    width=7)
        tabla.add_column("RSS kB",  style="magenta",width=9)
        tabla.add_column("Threads", style="yellow", width=8)
        tabla.add_column("Comando", style="white")
        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 15):
            tabla.add_row(
                str(info['pid']),
                str(info['ppid']),
                str(info['usuario'])[:12],
                str(info['estado']),
                str(info.get('cpu_pct', '0.0')) + '%',
                str(info.get('vm_rss', '?')),
                str(info['threads']),
                str(info['comando'])[:50],
                style=estilo
            )
 
    elif vista_activa == 'sistema':
        tabla = Table(title=f"Detalle — Sistema Global [intervalo:{_intervalo_str()}]")
        tabla.add_column("Métrica", style="cyan",  width=20)
        tabla.add_column("Valor",   style="green")
        tabla.add_row("CPU %",      str(datos.get('cpu_pct', '?')) + "%")
        tabla.add_row("Load 1min",  str(datos.get('loadavg', {}).get('load_1', '?')))
        tabla.add_row("Load 5min",  str(datos.get('loadavg', {}).get('load_5', '?')))
        tabla.add_row("Mem Total",  str(datos.get('mem_total', '?')) + " kB")
        tabla.add_row("Mem Free",   str(datos.get('mem_free',  '?')) + " kB")
        tabla.add_row("Mem Cached", str(datos.get('mem_cached','?')) + " kB")
 
    elif vista_activa == 'memoria':
        tabla = Table(title=f"Detalle — Memoria [intervalo:{_intervalo_str()}]{filtro_str}")
        tabla.add_column("PID",      style="cyan",   width=8)
        tabla.add_column("Nombre",   style="white",  width=15)
        tabla.add_column("VmRSS",    style="green",  width=12)
        tabla.add_column("VmSize",   style="yellow", width=12)
        tabla.add_column("VmSwap",   style="red",    width=12)
        tabla.add_column("Heap kB",  style="blue",   width=10)
        tabla.add_column("Stack kB", style="blue",   width=10)
        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 12):
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
        tabla = Table(title=f"Detalle — FDs [intervalo:{_intervalo_str()}]{filtro_str}")
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("Total FDs", style="yellow", width=10)
        tabla.add_column("FD",        style="blue",   width=6)
        tabla.add_column("Tipo",      style="green",  width=8)
        tabla.add_column("Destino",   style="white")
        # Verbose: muestra más FDs por proceso
        max_fds = 5 if verbose else 1
        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 10):
            lista = info.get('fds', [])
            if not lista:
                tabla.add_row(str(pid), info['nombre'][:15], str(info['total']), '-', '-', '-', style=estilo)
                continue
            for fd_item in lista[:max_fds]:
                tabla.add_row(
                    str(pid), info['nombre'][:15], str(info['total']),
                    str(fd_item['fd']), str(fd_item['tipo']), str(fd_item['destino'])[:40],
                    style=estilo
                )
 
    elif vista_activa == 'threads':
        tabla = Table(title=f"Detalle — Threads [intervalo:{_intervalo_str()}]{filtro_str}")
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("TID",       style="blue",   width=8)
        tabla.add_column("Estado",    style="green",  width=8)
        tabla.add_column("Vol ctx",   style="yellow", width=10)
        tabla.add_column("NoVol ctx", style="red",    width=10)
        # Verbose: muestra más threads por proceso
        max_threads = 5 if verbose else 2
        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 10):
            lista = info.get('threads', [])
            if not lista:
                tabla.add_row(str(pid), info['nombre'][:15], '-', '-', '-', '-', style=estilo)
                continue
            for t in lista[:max_threads]:
                tabla.add_row(
                    str(pid), info['nombre'][:15],
                    str(t['tid']), str(t['estado']),
                    str(t['vol_ctx']), str(t['nonvol_ctx']),
                    style=estilo
                )
 
    elif vista_activa == 'senales':
        tabla = Table(title=f"Detalle — Señales [intervalo:{_intervalo_str()}]{filtro_str}")
        tabla.add_column("PID",        style="cyan",   width=8)
        tabla.add_column("Nombre",     style="white",  width=15)
        tabla.add_column("Bloqueadas", style="red",    width=20)
        tabla.add_column("Ignoradas",  style="yellow", width=20)
        tabla.add_column("Capturadas", style="green",  width=20)
        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 10):
            tabla.add_row(
                str(pid), info['nombre'][:15],
                ', '.join(info['bloqueadas'])[:20] or '-',
                ', '.join(info['ignoradas'])[:20]  or '-',
                ', '.join(info['capturadas'])[:20] or '-',
                style=estilo
            )
 
    elif vista_activa == 'scheduling':
        tabla = Table(title=f"Detalle — Scheduling [intervalo:{_intervalo_str()}]{filtro_str}")
        tabla.add_column("PID",       style="cyan",   width=8)
        tabla.add_column("Nombre",    style="white",  width=15)
        tabla.add_column("Nice",      style="yellow", width=6)
        tabla.add_column("Política",  style="green",  width=10)
        tabla.add_column("CPU",       style="blue",   width=8)
        tabla.add_column("Vol ctx",   style="yellow", width=10)
        tabla.add_column("NoVol ctx", style="red",    width=10)
        for i, pid, info, estilo in _agregar_filas_con_navegacion(tabla, items, 10):
            tabla.add_row(
                str(pid), info['nombre'][:15],
                str(info['nice']), str(info['politica']),
                str(info['cpu_affinidad']),
                str(info['vol_ctx']), str(info['nonvol_ctx']),
                style=estilo
            )
 
    else:
        tabla = Table(title=f"Vista: {vista_activa} (próximamente)")
 
    return tabla
 
 
def construir_tabla(snapshot):
    layout = Layout()
    layout.split_column(
        Layout(name="lista",   ratio=2),
        Layout(name="detalle", ratio=3),
    )
    layout["lista"].update(Panel(construir_lista_procesos(snapshot), title="Lista de Procesos"))
    layout["detalle"].update(Panel(construir_detalle(snapshot), title=f"Vista: {vista_activa.upper()}"))
    return layout
 
 
def display(snapshot, intervalos, intervalo=2.0):
    global _intervalos
    _intervalos = intervalos
 
    print(f"[Display] Iniciado con PID {mp.current_process().pid}", file=sys.stderr)
 
    t_teclado = threading.Thread(target=leer_teclado, daemon=True)
    t_teclado.start()
 
    while 'resumen' not in snapshot:
        time.sleep(0.5)
 
    with Live(console=console, refresh_per_second=1, auto_refresh=False) as live:
        while True:
            try:
                if not en_filtro:
                    tabla = construir_tabla(snapshot)
                    live.update(tabla)
                    live.refresh()
            except Exception:
                pass
            time.sleep(0.5)
