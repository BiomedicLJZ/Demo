# Agente de ventas

Vendedor conversacional en CLI: Deep Agents (LangChain) + NVIDIA NIM (principal) con fallback a Gemini (Google AI Studio) + PostgreSQL.
Ciclo completo: catálogo → cliente → cotización → pedido (descuenta stock) → pago simulado → comprobante.

## Puesta en marcha

    cp .env.example .env          # completa NVIDIA_API_KEY, GOOGLE_API_KEY, NIM_MODEL, GEMINI_MODEL
    docker compose up -d --wait   # Postgres 17 en :5433 con esquema y datos de ejemplo
    uv run ventas

Ejecuta `ventas` desde la raíz del proyecto: solo se lee el `.env` del directorio actual (no se heredan los de directorios padre).

## Web UI y API REST

    uv run ventas-web             # http://127.0.0.1:8000 (solo loopback, sin autenticación: demo local)

Con Docker (app + Postgres, usa las claves de `.env`; dentro de la red de compose la BD es `db:5432`):

    docker compose --profile app up -d --build --wait   # http://127.0.0.1:8000
    docker compose --profile app down                   # detener (los datos persisten en el volumen pgdata)

La app es un perfil aparte: `docker compose up -d --wait` sigue levantando solo la BD. Si ya tienes `uv run ventas-web` corriendo, libera el puerto 8000 antes. `.env` no se copia a la imagen (`.dockerignore`); las claves entran en tiempo de ejecución.

Vista de cliente por defecto; `/?dev` muestra además las herramientas llamadas y qué modelo respondió. En la web Gemini responde primero y NIM es el respaldo (el CLI conserva el orden inverso).

`POST /api/chat` `{"mensaje", "thread_id"?}` responde por SSE (`herramienta`, `resultado`, `token`, `error`, `fin`);
`GET /api/catalogo` · `GET /api/pedidos/{id}` · `GET /api/modelo` · docs interactivas en `/docs`.

## Comandos

`/ayuda` `/nuevo` `/modelo` `/herramientas` `/todos` `/catalogo` `/pedido <id>` `/limpiar` `/salir` — escribe `/` para autocompletar.

## Pruebas

    docker compose up -d --wait
    uv run pytest                       # usa la BD `ventas_test` (se vacía en cada prueba)
    uv run python scripts/humo.py       # manual, con LLMs reales

## Notas

- Escrituras solo por herramientas tipadas; `consulta_sql` es de solo lectura (rol `ventas_ro`, 5 s, 200 filas).
- El stock se descuenta al crear el pedido; no hay cancelaciones (fuera de alcance).
- `ventas_ro` lee todas las tablas, incluidos datos de clientes: pensado para uso por personal de ventas.
- Contraseñas de la BD (`ventas_rw`/`ventas_ro`/`postgres`) son de desarrollo; no usar tal cual en producción.
