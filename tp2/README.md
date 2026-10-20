# TP2 — Plataforma de Tareas Distribuidas

Servicio HTTP (FastAPI) que recibe tareas, las encola en una `asyncio.Queue`
y las ejecuta con un pool de workers asíncronos.

> Estado: en desarrollo. Las tres tareas andan; falta cancelación de tareas
> en ejecución, apagado ordenado, mediciones e informe.

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
│   └── modelos.py   # Estados, Tarea y el cuerpo del POST
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

<!-- Pendiente: diagrama, decisiones de diseño, mediciones, conceptos del
curso, limitaciones y lo que aprendí. -->
