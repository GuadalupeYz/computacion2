# dudas.md — TP1 Monitor de Procesos

Dudas que surgieron durante el desarrollo y sus respuestas.

---

## ¿Por qué el dump JSON queda dentro del contenedor y no en el host?

Cuando el monitor corre dentro de Docker y recibe SIGUSR1, el handler abre un archivo con `open('/app/dump_<timestamp>.json', 'w')`. Ese path existe dentro del filesystem del contenedor, no en el host. Docker aísla el filesystem por diseño.

Para verlo: `docker exec <contenedor> ls /app/dump_*.json`

Si se quisiera que aparezca en el host, habría que montar un volumen: `- ./dumps:/app/dumps` en el docker-compose y escribir ahí.

---

## ¿Por qué `multiprocessing` cierra `sys.stdin` en los procesos hijos?

Lo descubrí cuando el lector de teclado fallaba con `termios.error` dentro del proceso display. La causa: `multiprocessing` reemplaza `stdin` por `/dev/null` en cada proceso hijo para evitar que múltiples procesos lean de la misma terminal de forma impredecible.

La solución fue abrir `/dev/tty` directamente:
```python
tty_fd = os.open('/dev/tty', os.O_RDONLY)
```
`/dev/tty` siempre referencia la terminal controladora del proceso, independientemente de cómo esté `stdin`.

---

## ¿Por qué `tty.setcbreak` y no `tty.setraw`?

`setraw` desactiva el procesamiento de señales de la terminal (Ctrl+C deja de generar SIGINT) y rompe el renderizado de `rich Live`. `setcbreak` es más suave: desactiva el buffering de línea pero mantiene el procesamiento de señales. Funciona bien con `rich`.

---

## ¿Por qué `manager.Lock()` y no `mp.Lock()`?

El Lock tiene que vivir en el mismo proceso servidor que el `Manager.dict`. Un `mp.Lock()` normal no puede pasarse correctamente a través del Manager. Crearlo con `manager.Lock()` garantiza que vive en el mismo espacio que el diccionario.

---

## ¿Por qué una Queue por analizador y no una sola?

Una `Queue` es FIFO con semántica de un solo consumidor: el primero en hacer `get()` saca el dato y los demás no lo ven. Si los 6 analizadores compartieran una Queue, solo el más rápido recibiría cada snapshot de PIDs.

---

## ¿Por qué `Value` para los intervalos y no `Manager.dict`?

`Manager.dict` tiene overhead de IPC en cada acceso (pasa por el proceso servidor). Los intervalos se leen en cada iteración del loop de cada analizador, que puede ser muy frecuente. `Value` usa `mmap` con `MAP_SHARED`: memoria compartida directa sin proceso intermediario, apropiada para un escalar que se accede frecuentemente.

---

## ¿Por qué `docker compose up --build` no permite usar el teclado?

Con `docker compose up`, Docker Compose no conecta el stdin de la terminal directamente al contenedor aunque tengas `stdin_open: true` y `tty: true`. La solución es usar `docker compose run --rm monitor`, que sí conecta el stdin, o hacer `docker attach <contenedor>` después del `up`.