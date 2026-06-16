import os

def get_pids():
    """Devuelve lista de PIDs activos leyendo /proc."""
    pids = []
    for entrada in os.listdir('/proc'):
        if entrada.isdigit():
            pids.append(int(entrada))
    return pids


def read_status(pid):
    """Parsea /proc/<pid>/status y devuelve un dict clave:valor."""
    resultado = {}
    try:
        with open(f'/proc/{pid}/status', 'r') as f:
            for linea in f:
                if ':' in linea:
                    clave, valor = linea.split(':', 1)
                    resultado[clave.strip()] = valor.strip()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return resultado


def read_stat(pid):
    """Parsea /proc/<pid>/stat y devuelve lista de campos."""
    try:
        with open(f'/proc/{pid}/stat', 'r') as f:
            contenido = f.read()
        # El nombre del proceso puede tener espacios y está entre paréntesis
        # Ej: "123 (mi proceso) S 456 ..."
        inicio = contenido.index('(')
        fin = contenido.rindex(')')
        nombre = contenido[inicio+1:fin]
        resto = contenido[fin+2:].split()
        campos = [str(pid), nombre] + resto
        return campos
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return None