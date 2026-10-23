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

<!-- Pendiente: diagrama, decisiones de diseño, conceptos del curso,
limitaciones y lo que aprendí. -->
