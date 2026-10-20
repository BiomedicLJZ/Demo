# Agente de ventas (Deep Agent) — Diseño

Fecha: 2026-10-16 · Estado: aprobada; implementación según docs/superpowers/plans/2026-10-16-agente-ventas.md

## 1. Objetivo y alcance

Un **vendedor conversacional** en CLI que atiende al cliente de punta a punta y escribe en PostgreSQL:

catálogo/stock → registrar cliente → cotización → pedido (descuenta inventario) → pago **simulado** → comprobante (registro en BD).

- LLM principal: **AWS Bedrock**. Fallback: **NVIDIA NIM** y después **Google AI Studio (Gemini)**.
- Framework: **LangChain Deep Agents** (`deepagents`).
- Entrada: CLI con Rich, comandos slash y autocompletado.
- Idioma: español.
- **Fuera de alcance (v1):** pasarela de pago real, cancelaciones/devoluciones/postventa, persistencia del historial entre ejecuciones del CLI, subagentes propios, autenticación de usuarios.

## 2. Decisiones

| Tema | Decisión |
|---|---|
| Acceso a BD | **Híbrido**: escrituras solo por herramientas tipadas (transacción en Python); lecturas libres por `consulta_sql` con rol de solo lectura |
| Agente | Un solo Deep Agent, sin subagentes propios. `write_todos` viene de `TodoListMiddleware` (Deep Agents 0.7.26 no lo trae) |
| Fallback | `ModelFallbackMiddleware` (langchain): Bedrock → NIM → Gemini, por llamada al modelo |
| Memoria | `InMemorySaver`, historial por `thread_id` |
| Dinero | `NUMERIC(12,2)`; precios y totales calculados en código desde la BD, nunca por el LLM |
| Impuesto | Tasa única `TASA_IMPUESTO` (default 0.16) |

## 3. Estructura

```
db/            schema.sql, seed.sql, docker-compose.yml
src/ventas/
  config.py    variables de entorno
  models.py    ChatNVIDIA + ChatGoogleGenerativeAI
  db.py        pool rw (herramientas) y pool ro (consulta_sql, /catalogo, /pedido)
  servicio.py  reglas de negocio (única capa que escribe); lo usan tools.py y el CLI
  tools.py     6 herramientas tipadas + consulta_sql
  agent.py     create_deep_agent(...)
  cli/         app.py (loop), commands.py (slash), render.py (Rich)
tests/
```

## 4. Esquema de datos

| Tabla | Campos clave |
|---|---|
| `clientes` | `id`, `nombre`, `email UNIQUE`, `telefono` |
| `productos` | `id`, `sku UNIQUE`, `nombre`, `precio`, `stock CHECK (stock >= 0)`, `activo` |
| `pedidos` | `id`, `cliente_id`, `estado` (`pendiente_pago` \| `pagado`), `subtotal`, `impuesto`, `total`, `creado_en` |
| `pedido_items` | `pedido_id`, `producto_id`, `cantidad CHECK (cantidad > 0)`, `precio_unitario` (copia al momento de la venta) |
| `pagos` | `pedido_id UNIQUE`, `monto`, `metodo`, `referencia`, `pagado_en` |
| `comprobantes` | `pedido_id UNIQUE`, `numero` (`COMP-000001`, secuencia), `emitido_en` |

Roles: `ventas_rw` (DML sobre las tablas) y `ventas_ro` (`SELECT`, `default_transaction_read_only = on`).
Datos semilla: ~15 productos genéricos (accesorios de tecnología) y 5 clientes.

## 5. Herramientas

Escritura (tipadas, español, errores como `ErrorDeNegocio`):

1. `buscar_productos(texto)` — por nombre o SKU; devuelve precio y stock.
2. `registrar_cliente(nombre, email, telefono?)` — busca por email o crea.
3. `cotizar(items)` — líneas, subtotal, impuesto y total; no persiste.
4. `crear_pedido(cliente_id, items)` — una transacción: `SELECT … FOR UPDATE` en orden de id, valida stock, descuenta, inserta pedido e items, estado `pendiente_pago`.
5. `registrar_pago(pedido_id, monto, metodo)` — simulado; exige `pendiente_pago` y monto exacto; idempotente por `UNIQUE`; pedido pasa a `pagado`.
6. `emitir_comprobante(pedido_id)` — solo si `pagado`; un comprobante por pedido.

El LLM solo envía `sku` y `cantidad` (nunca precios).

Lectura: `consulta_sql(sql)` — una sola sentencia `SELECT`, rol `ventas_ro`, `statement_timeout` 5 s, máximo 200 filas.

## 6. Modelos, fallback y configuración

Variables (`.env`, con `.env.example`): `BEDROCK_API_KEY`, `BEDROCK_MODEL`, `NVIDIA_API_KEY`, `GOOGLE_API_KEY`, `NIM_MODEL`, `GEMINI_MODEL`, `DATABASE_URL`, `DATABASE_URL_RO`, `TASA_IMPUESTO`.
Los nombres de modelo **no tienen default en código**; el arranque falla con mensaje claro si faltan.

```python
create_deep_agent(
    model=ChatBedrockConverse(model=BEDROCK_MODEL, api_key=BEDROCK_API_KEY, region_name="us-east-1"),
    tools=[...6 tipadas, consulta_sql],
    middleware=[TodoListMiddleware(), ModelFallbackMiddleware(ChatNVIDIA(model=NIM_MODEL), ChatGoogleGenerativeAI(model=GEMINI_MODEL))],
    system_prompt=<vendedor en español + reglas de negocio>,
    checkpointer=InMemorySaver(),
)
```

- El fallback se decide **por llamada**: con Bedrock caído, cada turno paga su timeout antes de pasar a NIM (y luego a Gemini).
- El proveedor que respondió se lee de `response_metadata["model_name"]` del último `AIMessage`.
- Si fallan ambos: error legible en el CLI, la sesión sigue viva.

APIs verificadas en entorno desechable: `deepagents` 0.7.26, `langchain` 1.4.6, `langchain-nvidia-ai-endpoints` 1.5.0, `langchain-google-genai` 4.4.2; `create_deep_agent(model, tools, *, system_prompt, middleware, checkpointer, ...)` y `ModelFallbackMiddleware(first_model, *additional_models)` existen con esas firmas.

## 7. CLI

- **Entrada:** `prompt_toolkit`, autocompletado al escribir `/` (comando + descripción), historial.
- **Salida:** `rich` — banner, spinner, líneas tenues por herramienta (`⚙ cotizar(...)`), respuesta final en `Panel` con Markdown, `Table` para catálogo/pedidos, pie con proveedor (`Bedrock`, `NIM ↩ fallback` o `Gemini ↩ fallback`).
- **Comandos:** `/ayuda`, `/nuevo`, `/modelo`, `/herramientas`, `/todos`, `/limpiar`, `/salir`, `/catalogo`, `/pedido <id>`.
- `/catalogo` y `/pedido <id>` consultan la BD con el pool `ro`, sin pasar por el LLM.
- `/herramientas` muestra las de negocio y marca las integradas de Deep Agents.

## 8. Errores y pruebas

- Errores de negocio (sin stock, SKU inexistente, monto distinto): `ErrorDeNegocio` con mensaje claro que el agente explica al cliente. Errores inesperados de BD/red: se registran y el agente responde algo genérico.
- `pytest` contra Postgres real en Docker (BD `ventas_test` reiniciada con TRUNCATE por prueba, porque las herramientas abren sus propias conexiones):
  - `crear_pedido`: feliz, stock insuficiente, SKU inexistente; prueba con hilos sobre la última unidad (sin sobreventa).
  - `registrar_pago`: monto incorrecto, pago doble, pedido ya pagado.
  - `emitir_comprobante`: solo con pedido pagado, uno por pedido.
  - `consulta_sql`: rechaza `INSERT`/`DROP`/multi-sentencia; respeta límite de filas y timeout.
  - Fallback: modelo falso que falla + modelo falso de respaldo, sin red; el pie indica el fallback.
  - CLI: completer para `/` y `/p`; parser de comandos incl. `/pedido <id>`.
- Agente con LLMs reales: solo script de humo manual con claves del usuario.

## 9. Limitaciones y riesgos conocidos

- El stock se descuenta al crear el pedido; un pedido que nunca se paga retiene stock (cancelar está fuera de alcance).
- `ventas_ro` lee todas las tablas, incluidos datos de clientes. Aceptable mientras el CLI lo opere personal de ventas; si un cliente final habla directo con el agente, acotar a vistas.
- Verificado el 2026-10-16: el backend de archivos por defecto es `StateBackend` (memoria); `execute` devuelve error en backends no-sandbox; las herramientas integradas no se ocultan. Sin verificar hasta el humo (`scripts/humo.py`, requiere claves reales): qué modelos NIM/Gemini sostienen tool-calling con el schema `list[Item]` y si `response_metadata["model_name"]` de NIM coincide con `NIM_MODEL`.
- `.env`: solo se lee el del directorio actual. `load_dotenv()` sin argumentos busca hacia arriba desde el módulo y cargaba el `.env` de `/home/biomedic-ljz/Projects/` (claves de otros proyectos); corregido con prueba.
- `uv` dentro de un workspace ajeno: `uv init` sí añadió `Consulting` a los miembros del padre y se revirtió a mano; verificado que un proyecto no-miembro es independiente y que `uv add` no tocó el `uv.lock` ni el `pyproject.toml` del padre.
- `requires-python = ">=3.14"`: las dependencias se instalaron y la suite pasa en CPython 3.14.7. `google.genai` emite una `DeprecationWarning` externa en 3.14.
