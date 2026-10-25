# TP2 — Plataforma de Tareas Distribuidas

Servicio HTTP (FastAPI) que recibe tareas, las encola en una `asyncio.Queue`
y las ejecuta con un pool de workers asíncronos.

> Estado: en desarrollo. Lo obligatorio del sistema está completo; faltan
> las mediciones y el informe.

## Cómo levantarlo

```bash
cd tp2
docker compose up --build
```

La API queda en `http://localhost:8000` (documentación interactiva en `/docs`).

Variables de entorno (en `docker-compose.yml`):

| Variable | Default | Qué hace |
|---|---|---|
| `WORKERS` | 4 | Cantidad de workers del pool |
| `TIMEOUT_DEFAULT` | 30 | Timeout en segundos si la tarea no trae uno |
| `COLA_MAX` | 100 | Tareas que pueden esperar en la cola; si se llena, `POST` responde 503 |
| `PROCESOS` | cantidad de CPUs | Procesos del `ProcessPoolExecutor` para `hashear` |
| `TIMEOUT_HTTP` | 10 | Timeout en segundos de cada URL en `descargar` |
| `DESCARGAS_MAX` | 20 | Descargas simultáneas como máximo (entre todas las tareas) |
| `APAGADO_MAX` | 10 | Segundos que el apagado espera a las tareas en curso |
| `ESTADO_DIR` | `estados` | Carpeta de los volcados `estado_<timestamp>.json` |
| `HASH_SIN_EXECUTOR` | 0 | Con `1`, `hashear` corre en el event loop (para medir el bloqueo) |

## Ejemplos

```bash
# Encolar (responde al instante con el id)
curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "esperar", "parametros": {"segundos": 5}}'

# Con timeout propio
curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "esperar", "parametros": {"segundos": 10}, "timeout": 2}'

curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "descargar", "parametros": {"urls": ["https://example.com"]}}'

curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "hashear", "parametros": {"texto": "hola", "iteraciones": 1000000}}'

curl localhost:8000/tareas                    # todas
curl 'localhost:8000/tareas?estado=ejecutando' # filtradas por estado
curl localhost:8000/tareas/<id>               # una
curl -X DELETE localhost:8000/tareas/<id>     # cancelar
curl localhost:8000/estadisticas
```

## Estructura

```
tp2/
├── src/
│   ├── main.py      # API FastAPI y arranque (lifespan)
│   ├── cola.py      # PoolWorkers: asyncio.Queue + N corrutinas worker
│   ├── tareas.py    # Implementación de cada tipo de tarea
│   ├── persistencia.py  # Volcado a JSON al apagar y aviso al arrancar
│   └── modelos.py   # Estados, Tarea y el cuerpo del POST
├── mediciones/      # Scripts de las tres mediciones
├── estados/         # Volcados (se crea solo, no se sube al repo)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Arquitectura

### Componentes

```
                   ┌──────────────────────────────────────────────────────┐
                   │  Proceso principal: uvicorn + un solo event loop     │
                   │                                                      │
  Cliente HTTP ───>│  API FastAPI (main.py)                               │
                   │   POST   /tareas        202 · 422 · 503              │
                   │   GET    /tareas        ?estado=...                  │
                   │   GET    /tareas/{id}   404                          │
                   │   DELETE /tareas/{id}   404 · 409                    │
                   │   GET    /estadisticas                               │
                   │        │ put_nowait(id)            ▲ lee el estado   │
                   │        v                           │                 │
                   │  asyncio.Queue(maxsize=COLA_MAX)   │                 │
                   │        │ await get()               │                 │
                   │        v                           │                 │
                   │  N workers (corrutinas) ───────> dict id -> Tarea    │
                   │        │  cada tarea corre en su propia asyncio.Task │
                   │        │  con wait_for(timeout)                      │
                   │        ├── esperar:   await asyncio.sleep            │
                   │        ├── descargar: httpx.AsyncClient + gather     │
                   │        │              + Semaphore(DESCARGAS_MAX)     │
                   │        └── hashear:   await run_in_executor ──┐      │
                   └───────────────────────────────────────────────┼──────┘
                                                                   v
                                          ProcessPoolExecutor (PROCESOS hijos)
                                          hash_iterado() en paralelo, fuera
                                          del event loop

  Al apagar:  dict id -> Tarea ──> estados/estado_<timestamp>.json
```

Todo lo de la caja corre en **un solo hilo**: la API, la cola, los workers y
las descargas son corrutinas que comparten el event loop. Lo único que sale
de ese hilo es el cálculo de `hashear`, que va a procesos aparte.

### Flujo de una tarea

1. **`POST /tareas`.** Pydantic valida el cuerpo (si el tipo no existe, 422).
   `encolar()` crea la `Tarea` en estado `pendiente` y hace `put_nowait` de su
   id en la cola. Si la cola está llena, responde 503. Si entró, responde
   **202 al instante**: el endpoint nunca espera a que la tarea se ejecute.
2. **Un worker la saca** con `await cola.get()`. Mientras la cola está vacía,
   los workers están suspendidos en ese `await` sin consumir CPU.
3. **Si la cancelaron mientras esperaba**, el worker la descarta. Si no, la
   pasa a `ejecutando` y lanza la ejecución como una `asyncio.Task` propia,
   envuelta en `asyncio.wait_for(..., timeout)`, y la guarda en `_en_curso`
   para que `DELETE` pueda encontrarla.
4. **La ejecución corre.** Cada `await` adentro (el `sleep`, la respuesta de
   la red, el *future* del executor) es un punto donde el loop atiende a los
   demás: otros workers, otros pedidos HTTP.
5. **Termina** de una de cuatro formas: devuelve un resultado (`completada`),
   lanza una excepción o vence el timeout (`fallida`, con el motivo en
   `error`), o la cancelan (`cancelada`). En el `finally` el worker la saca de
   `_en_curso`, baja el contador de ocupados y llama a `task_done()`. Después
   vuelve a `await cola.get()` por la siguiente.
6. **El cliente consulta** con `GET /tareas/{id}` cuando quiere: el estado y el
   resultado están en el diccionario en memoria.

### Estados

```
                  DELETE (descartada al salir de la cola)
           ┌──────────────────────────────────────────────┐
           │                                              v
      pendiente ──> ejecutando ──> completada         cancelada
                        │                                 ^
                        ├──> fallida  (excepción o timeout)
                        │                                 │
                        └─────────────────────────────────┘
                          DELETE, o apagado con el límite vencido
```

`completada`, `fallida` y `cancelada` son finales: un `DELETE` sobre una
tarea en esos estados responde 409.

### Ciclo de vida del servidor

**Al arrancar** (`lifespan`, antes del `yield`):

1. Se informa por log si hay un volcado previo en `estados/`.
2. Se crean una sola vez el `ProcessPoolExecutor` y el `httpx.AsyncClient`,
   que se reutilizan durante toda la vida del servidor.
3. Se lanzan los `WORKERS` workers con `asyncio.create_task`.

**Al recibir `SIGTERM` o `SIGINT`** (`docker compose down`, Ctrl+C):

1. uvicorn deja de aceptar conexiones, termina los pedidos HTTP en curso y
   ejecuta la parte de apagado del `lifespan`.
2. El pool deja de aceptar tareas (`POST` responde 503) y marca como
   canceladas las que seguían pendientes.
3. Pone un centinela por worker en la cola. Cada worker termina la tarea que
   tenía y sale cuando saca el centinela.
4. Espera a los workers hasta `APAGADO_MAX` segundos. Si alguno no terminó,
   lo cancela, y su tarea queda `cancelada por apagado`. Si había un hash en
   curso, mata los procesos hijos con `SIGKILL`.
5. Vuelca el estado a `estados/estado_<timestamp>.json`.
6. Cierra el cliente HTTP y el executor.

## Decisiones de diseño

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

Porque las dos esperan de forma muy distinta. `queue.Queue.get()` bloquea
**el hilo** hasta que haya un elemento. Acá hay un solo hilo, el del event
loop, así que un worker esperando en una `queue.Queue` vacía congelaría la
API, los demás workers y todo lo demás. `queue.Queue` está pensada para
threads: sus locks internos coordinan hilos que el sistema operativo puede
interrumpir en cualquier momento.

`await asyncio.Queue.get()` en cambio **suspende solo esa corrutina** y le
devuelve el control al loop. Los cuatro workers pueden estar esperando
trabajo a la vez sin consumir CPU ni frenar a nadie, y cuando la API hace
`put_nowait` el loop despierta a uno.

Por la misma razón el pool **no necesita `Lock`**: todo corre en un hilo y
el loop solo cambia de corrutina en un `await`. Las secciones que tocan
estado compartido (el diccionario de tareas, `_en_curso`, el contador de
ocupados) no tienen ningún `await` en el medio, así que son atómicas por
construcción. Si algún día hiciera falta un `await` entre leer y escribir
ese estado, ahí sí habría que usar `asyncio.Lock` (clase 20).

### Cola con límite: 503 en vez de crecer sin fin

La cola se crea con `maxsize=COLA_MAX`. Sin límite, un cliente que manda
tareas más rápido de lo que se procesan haría crecer la memoria hasta
agotarla. Con límite, el sistema rechaza lo que no va a poder hacer: es el
*backpressure* de la clase 21.

En `encolar()` uso `put_nowait()` y atrapo `asyncio.QueueFull` para
responder 503, en vez de `await put()`. Con `await put()` el pedido HTTP se
quedaría esperando a que se libere un lugar, y el enunciado pide que el
`POST` responda en el acto. Además la tarea se registra en el diccionario
**después** de entrar en la cola: si fuera al revés, una tarea rechazada
quedaría `pendiente` para siempre.

### ¿Cómo evito que una tarea CPU-bound congele la API?

`hashear` llama a `hash_iterado`, una función común sin ningún `await`, a
través de `loop.run_in_executor(pool_cpu, hash_iterado, texto, iteraciones)`.
El cálculo corre en un proceso hijo del `ProcessPoolExecutor` y la corrutina
solo hace `await` sobre el *future*: mientras espera, el loop sigue atendiendo
pedidos. La medición 2 lo muestra con números: sin executor el peor GET tardó
6539 ms, con executor 7.9 ms.

Elegí **procesos y no threads** (`asyncio.to_thread`) por el GIL: con threads,
un solo hash tampoco congelaría el loop, pero varios hashes a la vez se
turnarían para ejecutar bytecode y no correrían en paralelo. Con procesos,
cada uno tiene su intérprete y su GIL, y usan núcleos distintos (la medición
3 lo muestra: dos hashes tardan lo mismo que uno).

Dos detalles más:

- El pool se crea **una sola vez** en el `lifespan` y no por pedido: crear
  procesos es caro.
- `hash_iterado` es una función de módulo y no una lambda porque se manda al
  proceso hijo *pickleada*, y una lambda no se puede serializar.

### ¿Cómo implementé la cancelación, y qué pasa con los recursos a medio usar?

El worker no ejecuta la tarea directamente con `await`: la lanza como una
`asyncio.Task` propia y la guarda en `_en_curso[id]`. Así `DELETE` puede
cancelar **solo el trabajo**, y el worker sigue vivo para tomar la siguiente
tarea de la cola.

- **Si la tarea está `pendiente`**, `DELETE` la marca `cancelada` y listo: no
  la saca de la cola, pero el worker la descarta cuando la encuentra.
- **Si está `ejecutando`**, `DELETE` llama a `task.cancel()`, que inyecta un
  `CancelledError` en el próximo `await` de la ejecución. `cancel()` devuelve
  `False` si la tarea acababa de terminar, y en ese caso no la marco como
  cancelada.
- **El worker distingue quién canceló** con `asyncio.current_task().cancelling()`.
  Si es 0, la cancelación era para la tarea (vino de `DELETE`) y el worker
  sigue. Si es mayor que 0, lo están cancelando a él porque se apaga el
  servidor: marca la tarea y **relanza** el `CancelledError`. Tragárselo
  dejaría al worker vivo y el apagado colgado (clase 20).
- **El `finally`** saca la tarea de `_en_curso` y baja el contador de ocupados
  pase lo que pase, así no quedan referencias colgadas.

Qué pasa con los recursos según el tipo de tarea:

| Tarea | Al cancelarla |
|-------|---------------|
| `esperar` | El `asyncio.sleep` se interrumpe en el acto |
| `descargar` | El `CancelledError` entra en el `await cliente_http.get(...)`. httpx cierra esa conexión, `gather` cancela las demás descargas de la tarea, y el `async with` del semáforo lo libera al salir. No queda ninguna corrutina huérfana |
| `hashear` | La tarea queda `cancelada` y el worker se libera enseguida, pero el proceso hijo **termina ese hash igual**: a un proceso que está calculando no se le puede inyectar una excepción. Mientras tanto ocupa uno de los `PROCESOS` |

El timeout funciona con el mismo mecanismo: `asyncio.wait_for` cancela la
ejecución cuando vence y lanza `TimeoutError`, que el worker convierte en
`fallida` con el motivo en `error`.

Al apagar, si se vence `APAGADO_MAX` con un hash en curso, mato los procesos
hijos con `kill()` (`SIGKILL`) y no con `terminate()` (`SIGTERM`). Los hijos
nacen con `fork` y **heredan los handlers de señales del padre**, o sea el de
uvicorn, que ante `SIGTERM` solo prende una bandera y no sale. Lo descubrí
porque el apagado tardaba 43 s en vez de 1. `SIGKILL` lo maneja el kernel y no
se puede atrapar.

### ¿Qué pasa si un worker lanza una excepción no capturada?

Hay dos niveles:

1. **Si falla la tarea** (parámetros inválidos como `urls` vacía,
   `iteraciones` negativas o un `modo` que no existe), la excepción sale de
   la ejecución y `_ejecutar` la atrapa con `except Exception`: la tarea pasa
   a `fallida` con el tipo y el mensaje del error en el campo `error`. El
   cliente lo ve en `GET /tareas/{id}`. Los errores de red de `descargar` son
   un caso aparte: se registran por URL dentro del resultado, para que una URL
   caída no tire abajo las otras 19.
2. **Si falla algo del propio worker** fuera de eso, el bucle de `_worker`
   tiene otro `except Exception` que lo registra con `log.exception` (con el
   traceback completo) y sigue con la próxima tarea. El `task_done()` está en
   un `finally`, así que el contador de la cola baja igual.

Sin esto, una excepción terminaría la corrutina del worker en silencio: la
`Task` guardaría la excepción y nadie la miraría nunca, igual que los `Future`
que nadie consulta en el pool de la clase 14. El pool quedaría con un worker
menos sin que nadie se entere. `CancelledError` no entra en esos `except`
porque hereda de `BaseException`, así que la cancelación nunca se pierde.

### ¿Por qué httpx y no aiohttp?

Las dos son clientes HTTP asíncronos y cualquiera cumple el requisito de no
bloquear el loop (`requests` no, porque es sincrónica). Elegí **httpx**
porque:

- Su API es casi la de `requests` (`cliente.get(url)`, `respuesta.status_code`),
  así que el código se lee fácil.
- Es la que usamos en la clase 20, y FastAPI la usa para sus pruebas.
- Tiene timeouts configurables en el cliente y un pool de conexiones con
  keep-alive, que se nota en la medición 1.

aiohttp suele rendir algo mejor con miles de conexiones simultáneas, pero acá
el tope es `DESCARGAS_MAX` = 20 y esa diferencia no importa.

El cliente se crea **una vez** en el `lifespan` y lo comparten todas las
tareas, con un timeout por URL (`TIMEOUT_HTTP`) para que un servidor que no
responde no cuelgue la tarea. Un `asyncio.Semaphore(DESCARGAS_MAX)` global
limita las descargas simultáneas **entre todas las tareas**: sin él, 10 tareas
de 20 URLs abrirían 200 conexiones a la vez.

## Mediciones

Todas las corrí en mi máquina, con `docker compose up` y la configuración
por defecto del `docker-compose.yml` (`WORKERS=4`, `PROCESOS=2`,
`COLA_MAX=100`). Los scripts están en `mediciones/` y se ejecutan dentro
del contenedor, así no hace falta instalar nada en el host:

```bash
docker compose exec api python mediciones/<script>.py
```

<!-- Completar: modelo de CPU y cantidad de núcleos (salida de `lscpu` / `nproc`) -->

### 1. Concurrencia I/O: 20 descargas secuenciales contra 20 concurrentes

`medir_io.py` encola dos tareas `descargar` con las mismas 20 URLs
(`https://httpbin.org/delay/1`, que tarda 1 s en responder a propósito):
una en modo `secuencial`, que hace un `for` con `await` adentro, y otra en
modo `concurrente`, que usa `asyncio.gather`. Tres repeticiones:

| Modo | Promedio | Mínimo | Máximo |
|------|----------|--------|--------|
| secuencial | 26.08 s | 25.60 s | 26.55 s |
| concurrente | 2.67 s | 2.14 s | 3.58 s |

**Speedup: 9.8x.**

**Interpretación.** En el secuencial cada `await` suspende la tarea hasta
que esa descarga termina, y recién ahí arranca la siguiente: el tiempo es
la **suma** de las 20. Con `gather` las 20 corrutinas se lanzan juntas y,
mientras una espera la respuesta de la red, el loop avanza con las otras:
el tiempo es el de la **más lenta**.

Dos detalles de los números:

- **Cada descarga secuencial tardó ~1.3 s**, aunque una petición suelta a la
  misma URL con `curl` me dio 1.9 s. La diferencia es el *keep-alive*: las 20
  descargas usan el mismo `httpx.AsyncClient`, así que solo la primera paga
  la conexión TCP y el handshake TLS, y las demás reutilizan la conexión.
- **El speedup es 9.8x y no 20x** porque el concurrente siempre espera a la
  descarga más lenta, y entre 20 pedidos por internet alguno siempre tarda
  más de la cuenta (de ahí que el concurrente varíe entre 2.14 s y 3.58 s).
  Además httpbin es un servicio público compartido que puede atender más
  lento 20 pedidos simultáneos. El límite está en la red, no en el código:
  con demoras idénticas el speedup tendería a 20x.

### 2. El event loop bloqueado

`medir_bloqueo.py` encola un `hashear` de 10 millones de iteraciones y,
mientras corre, pide `GET /tareas` sin parar midiendo cada respuesta. Lo
corrí con el hash calculado directamente en la corrutina
(`HASH_SIN_EXECUTOR=1`) y con `run_in_executor` sobre el
`ProcessPoolExecutor` (`HASH_SIN_EXECUTOR=0`). Sin carga, un `GET /tareas`
tarda 1.2 ms.

| Corrida | Duración del hash | GET respondidos | GET promedio | Peor GET |
|---------|-------------------|-----------------|--------------|----------|
| sin executor | 6.54 s | 2 | 3270.0 ms | **6538.9 ms** |
| con executor | 8.56 s | 7763 | 1.1 ms | **7.9 ms** |

**Interpretación.** Sin executor, el `for` de `hash_iterado` no tiene
ningún `await`, así que el event loop no puede cambiar de corrutina hasta
que el cálculo termina. El GET que mandé apenas arrancó el hash esperó **los
6.5 s completos**: durante todo el cálculo la API respondió dos pedidos y
para cualquier cliente estuvo colgada. Lo mismo vale para los otros
workers, los timeouts y las cancelaciones: nada avanza.

Con executor, el cálculo corre en otro proceso y la corrutina solo hace
`await` sobre el *future*. El loop queda libre: respondió **7763 pedidos**
en el mismo lapso, a 1.1 ms cada uno, igual que sin carga. El peor caso bajó
de 6539 ms a 7.9 ms, unas 800 veces menos.

El hash tardó **más** con executor (8.56 s contra 6.54 s), y eso también es
esperable: el executor no acelera el cálculo, lo saca del loop. Durante esos
segundos el script y el servidor estaban procesando miles de GET, que
compiten por el CPU con el proceso que calcula.

### 3. Techo del pool

`medir_techo.py` encola N tareas de golpe, con N creciente, y mide el tiempo
total y la latencia de cada tarea (de encolada a terminada). Lo corrí con
los dos tipos de tarea, porque el techo no está en el mismo lugar.

**`esperar` de 1 s (I/O):**

| N | Tiempo total | Latencia promedio | Latencia máxima | Rechazadas (503) |
|---|--------------|-------------------|-----------------|------------------|
| 1 | 1.00 s | 1.00 s | 1.00 s | 0 |
| 2 | 1.00 s | 1.00 s | 1.00 s | 0 |
| 4 | 1.01 s | 1.00 s | 1.00 s | 0 |
| 8 | 2.01 s | 1.50 s | 2.00 s | 0 |
| 16 | 4.01 s | 2.49 s | 3.99 s | 0 |
| 32 | 8.02 s | 4.49 s | 7.98 s | 0 |
| 64 | 16.04 s | 8.48 s | 15.96 s | 0 |
| 128 | 26.06 s | 13.47 s | 25.94 s | 24 |

**`hashear` de 1 millón de iteraciones (CPU):**

| N | Tiempo total | Latencia promedio | Latencia máxima | Rechazadas (503) |
|---|--------------|-------------------|-----------------|------------------|
| 1 | 0.70 s | 0.70 s | 0.70 s | 0 |
| 2 | 0.71 s | 0.69 s | 0.70 s | 0 |
| 4 | 1.46 s | 1.09 s | 1.44 s | 0 |
| 8 | 2.82 s | 1.77 s | 2.79 s | 0 |
| 16 | 5.63 s | 3.13 s | 5.59 s | 0 |

**Interpretación.**

- **Con `esperar`, el límite es `WORKERS` = 4.** Hasta N = 4 todas tardan lo
  mismo que una sola. A partir de ahí el tiempo crece en escalones exactos de
  N / 4 segundos (8 → 2 s, 16 → 4 s, 64 → 16 s): las que sobran esperan su
  turno en la cola. Es el pool saturado de la clase 14: nadie es rechazado,
  pero la latencia crece. Es un límite **de configuración**, no de la
  máquina: esperar no consume CPU, y con más workers entrarían muchas más a
  la vez.
- **Con N = 128 aparecen los 503.** Entran 104 tareas (4 ejecutando y 100 en
  la cola, que es `COLA_MAX`) y las otras 24 se rechazan al instante. El
  sistema no se cae: rechaza lo que no puede encolar. Es la respuesta a
  "¿qué pasa si mando 10.000 tareas de golpe?": se llena la cola primero.
- **Con `hashear`, el límite es `PROCESOS` = 2, no los 4 workers.** Dos hashes
  tardan lo mismo que uno, pero con 4 el tiempo ya se duplica: el tercero
  espera un proceso libre aunque haya un worker desocupado. Acá el cuello de
  botella es el CPU, y lo fija el hardware: subir `PROCESOS` por encima de la
  cantidad de núcleos no ayuda, porque los procesos se turnan en los mismos
  núcleos.

## Conceptos del curso aplicados

**Productor-consumidor con corrutinas (clases 11 y 21).** El pool de workers
consume de una `asyncio.Queue` compartida (`cola.py`, `_worker`). Es el mismo
patrón productor-consumidor de la clase 11, pero con corrutinas en vez de
threads: la API produce con `put_nowait` y los workers consumen con
`await get()`. Acá no hace falta lock porque el event loop no interrumpe
entre `await`s, y ninguna sección que toca el estado compartido tiene un
`await` en el medio. El `task_done()` va en un `finally`, como se recomienda
en la clase 21, para que el contador de la cola baje aunque la tarea falle.

**Backpressure (clases 20 y 21).** `asyncio.Queue(maxsize=COLA_MAX)` cumple el
mismo rol que el `drain()` de la clase 20: frenar al productor cuando el
consumidor no da abasto. En vez de esperar, la API rechaza con 503: un
servidor que recibe pedidos de afuera no debería aceptar trabajo que no va a
poder hacer.

**El event loop y la cooperación (clases 17 y 18).** Cada `await` del código es
un punto donde la corrutina cede el control, igual que el `yield` del
scheduler cooperativo que construimos con generadores en la clase 18. Por
eso `tareas.esperar` usa `await asyncio.sleep()`: un `time.sleep()` no
cedería y congelaría al resto, que es exactamente lo que muestra la medición
2 con `hash_iterado` corriendo en el loop. Por debajo, el loop de uvicorn es un
`_UnixSelectorEventLoop`: usa `epoll`, el multiplexing de la clase 17, para
dormir hasta que algún socket tenga datos.

**HTTP y FastAPI (clase 19).** Los códigos de respuesta siguen la división
de la clase 19 entre error del cliente y del servidor: 202 para una tarea
aceptada pero no terminada, 404 si no existe, 409 si se intenta cancelar algo
ya finalizado, 422 cuando Pydantic rechaza el cuerpo y 503 cuando el servidor
no puede aceptar más (cola llena o apagándose). Todos los endpoints son
`async def` y ninguno bloquea: la clase 19 mostró que un `async def` con algo
bloqueante adentro es peor que un `def` común.

**Concurrencia de clientes con `gather` y `Semaphore` (clases 11 y 20).**
`tareas.descargar` lanza todas las descargas con `asyncio.gather`, el patrón
de la clase 20 para clientes concurrentes, y las acota con un
`asyncio.Semaphore`, la misma primitiva de la clase 11 en su versión async.
El `httpx.AsyncClient` se crea una sola vez y lleva timeout, las dos reglas
que da la clase 20 (reutilizar conexiones por el keep-alive de la clase 19, y
no confiar en que la red responda, la falacia de la clase 12).

**Cancelación y timeouts (clase 20).** `DELETE` usa `task.cancel()`, que no
mata nada: inyecta un `CancelledError` en el próximo `await`. De ahí sale la
limitación de `hashear`: un cálculo que no cede no se puede cancelar. El
worker relanza el `CancelledError` cuando la cancelación es para él, como
pide la clase 20, y limpia en un `finally`. El timeout de cada tarea es
`asyncio.wait_for`, que por dentro también es una cancelación.

**I/O-bound contra CPU-bound, y el GIL (clases 10, 14 y 21).** Las descargas
son I/O-bound: pasan casi todo el tiempo esperando, y eso asyncio lo resuelve
en un solo hilo. El hash es CPU-bound: asyncio no lo puede repartir, porque
hay un solo hilo. Por eso va a un `ProcessPoolExecutor` y no a un thread: con
el GIL de la clase 10, varios threads calculando se turnan y no corren en
paralelo. Es la tabla de decisión de las clases 14 y 21 aplicada.

**Executors y `Future` (clases 14, 21 y 22).** `run_in_executor` devuelve un
*future* sobre el que la corrutina hace `await`. El executor se crea una vez
en el `lifespan` (clase 21) y sus argumentos viajan pickleados, por eso
`hash_iterado` es una función de módulo. El `except Exception` con
`log.exception` del worker evita el problema de la clase 14: una excepción
guardada en un `Future` que nadie mira desaparece sin dejar rastro.

**Procesos, `fork` y señales (clases 4 y 6).** El apagado ordenado reúne
varias cosas del primer bloque. uvicorn instala un handler de `SIGTERM` y
`SIGINT` que solo marca un pedido de cierre, y el loop lo procesa después,
entre tareas: es la regla de la clase 6 (el handler hace lo mínimo) y la
misma idea que `loop.add_signal_handler` en la clase 20. Por eso el apagado
lo hago en el `lifespan` y no instalo handlers propios, que pisarían los de
uvicorn. Los workers del executor
son procesos hijos creados con `fork` (clase 4), y por eso heredan los
handlers de señales del padre: un `SIGTERM` no los terminaba, y hubo que
usar `SIGKILL`, que no se puede atrapar.

**Centinela para el apagado (clase 21).** Para parar los workers sin cortar lo
que están haciendo, `detener()` pone en la cola un `CENTINELA = object()` por
worker. Es un objeto único que se compara con `is`, así que nada que llegue
por la API se puede confundir con él. Cancelar a los workers queda como plan
B, solo si se vence `APAGADO_MAX`.

**Descriptores y el problema C10K (clases 13, 14 y 17).** Cada descarga abre
un socket, y cada socket consume un descriptor de archivo, un recurso
limitado por proceso (`ulimit -n`, clase 14). El semáforo de descargas y el
límite de la cola evitan que miles de tareas agoten los descriptores.
Atender muchas esperas en un solo hilo, en vez de un thread por cliente, es
la respuesta al problema C10K que planteó la clase 14.

<!-- Pendiente: limitaciones y lo que aprendí. -->
