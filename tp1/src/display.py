import time
import threading
import os, termios, tty
import multiprocessing as mp
from rich.console import Console
from rich.table import Table
from rich.live import Live
import threading

#Teclas 1 a 7 y r, m, f, t, s, p, g — ¿cambian las vistas?
#h o ? — ¿aparece la ayuda? ¿Podés salir con h de nuevo?
#+ y - — ¿cambia el intervalo visible en el título?
#q — ¿cierra limpiamente?

_lock_estado = threading.Lock()
console = Console()
vista_activa = 'resumen'
intervalo_actual = 2.0
mostrar_ayuda = False

def leer_teclado():
    global vista_activa, intervalo_actual, mostrar_ayuda
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
    import traceback
    try:
        tty_fd = os.open('/dev/tty', os.O_RDONLY)
        config_original = termios.tcgetattr(tty_fd)
        tty.setcbreak(tty_fd)
        while True:
            tecla = os.read(tty_fd, 1).decode(errors='replace')
            #print(f"[TECLADO] recibí: {repr(tecla)}", flush=True)
            print(f"[TECLADO] recibí: {repr(tecla)} ord={ord(tecla) if len(tecla)==1 else 'multi'}", flush=True) 

            if tecla in vistas:
                vista_activa = vistas[tecla]
            #elif tecla == '+':
               # intervalo_actual = min(intervalo_actual + 0.5, 30.0)
            elif tecla == '-':
                minimo = intervalos_minimos.get(vista_activa, 0.5)
                intervalo_actual = max(intervalo_actual - 0.5, minimo)
            elif tecla == '+': #nuevo 
                intervalo_actual = min(intervalo_actual + 0.5, 30.0)
                print(f"[TECLADO] intervalo ahora: {intervalo_actual}", flush=True)
            elif tecla in ('h', '?'):
                mostrar_ayuda = not mostrar_ayuda
            elif tecla == 'q':
                import signal
                os.kill(os.getppid(), signal.SIGTERM)
                break
    except Exception as e:
        print(f"[TECLADO] SE CAYÓ CON ERROR: {e}", flush=True)
        traceback.print_exc()
    finally:
        try:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, config_original)
            os.close(tty_fd)
        except:
            pass

def construir_ayuda():
    tabla = Table(title="Ayuda — Monitor de Procesos")
    tabla.add_column("Tecla",  style="cyan",  width=20)
    tabla.add_column("Acción", style="white")
    tabla.add_row("1-7 / r,m,f,t,s,p,g", "Cambiar vista")
    tabla.add_row("+",   "Aumentar intervalo")
    tabla.add_row("-",   "Disminuir intervalo")
    tabla.add_row("h / ?", "Mostrar/ocultar ayuda")
    tabla.add_row("q",   "Salir")
    return tabla

def construir_tabla(snapshot):
    global vista_activa, intervalo_actual, mostrar_ayuda
    ayuda = mostrar_ayuda
    
    if ayuda:
        return construir_ayuda()
    
    if vista_activa not in snapshot:
        return Table(title=f"Vista: {vista_activa} (sin datos aún)")

    datos = snapshot[vista_activa]

    if vista_activa == 'resumen':
        tabla = Table(title=f"Monitor de Procesos — Resumen [intervalo: {intervalo_actual:.1f}s]")   
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
        tabla = Table(title=f"Monitor de Procesos — Sistema Global [intervalo: {intervalo_actual:.1f}s]")    
        tabla.add_column("Métrica", style="cyan",  width=20)
        tabla.add_column("Valor",   style="green")
        tabla.add_row("CPU %",      str(datos.get('cpu_pct', '?')) + "%")
        tabla.add_row("Load 1min",  str(datos.get('loadavg', {}).get('load_1', '?')))
        tabla.add_row("Load 5min",  str(datos.get('loadavg', {}).get('load_5', '?')))
        tabla.add_row("Mem Total",  str(datos.get('mem_total', '?')) + " kB")
        tabla.add_row("Mem Free",   str(datos.get('mem_free',  '?')) + " kB")
        tabla.add_row("Mem Cached", str(datos.get('mem_cached','?')) + " kB")

    elif vista_activa == 'memoria':
        tabla = Table(title=f"Monitor de Procesos — Memoria [intervalo: {intervalo_actual:.1f}s]")   
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
        tabla = Table(title=f"Monitor de Procesos — File Descriptors [intervalo: {intervalo_actual:.1f}s]")  
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
        tabla = Table(title=f"Monitor de Procesos — Threads  [intervalo: {intervalo_actual:.1f}s]")
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
        tabla = Table(title=f"Monitor de Procesos — Señales  [intervalo: {intervalo_actual:.1f}s]")
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
        tabla = Table(title=f"Monitor de Procesos — Scheduling  [intervalo: {intervalo_actual:.1f}s]")
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
    global intervalo_actual
    intervalo_actual = intervalo
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
            time.sleep(intervalo_actual)  # usa la variable global
