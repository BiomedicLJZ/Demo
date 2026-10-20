"""API REST + UI web mínima. El chat responde por SSE: tokens a medida que el modelo escribe."""
import json
import os
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, Field

from ventas import servicio
from ventas.agent import construir_agente, herramientas_integradas
from ventas.cli.app import _texto
from ventas.config import ConfigError, cargar
from ventas.db import Db
from ventas.models import construir_modelos
from ventas.servicio import ErrorDeNegocio
from ventas.tools import construir_herramientas

INDEX = Path(__file__).with_name("index.html")


class Chat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None  # sin él se abre una conversación nueva; se devuelve en `fin`


def _sse(evento: str, datos: dict) -> str:
    return f"event: {evento}\ndata: {json.dumps(datos, ensure_ascii=False, default=str)}\n\n"


def _turno(agente, principal: str, thread_id: str, texto: str):
    config = {"configurable": {"thread_id": thread_id}}
    modelo, hubo_tokens = None, False
    try:
        for modo, datos in agente.stream({"messages": [("user", texto)]}, config,
                                         stream_mode=["messages", "updates"]):
            if modo == "messages":
                chunk, meta = datos
                if meta.get("langgraph_node") == "model" and isinstance(chunk, AIMessageChunk) \
                        and (t := _texto(chunk.content)):
                    hubo_tokens = True
                    yield _sse("token", {"texto": t})
                continue
            for nodo, upd in datos.items():
                if nodo not in ("model", "tools") or not isinstance(upd, dict):
                    continue  # otros nodos (middleware) pueden reemitir el historial entero
                msgs = upd.get("messages", [])
                for m in msgs if isinstance(msgs, list) else [msgs]:
                    if isinstance(m, AIMessage):
                        for tc in m.tool_calls:
                            yield _sse("herramienta", {"nombre": tc["name"], "args": tc["args"]})
                        modelo = m.response_metadata.get("model_name", modelo)
                        if not m.tool_calls and not hubo_tokens and (final := _texto(m.content)):
                            yield _sse("token", {"texto": final})  # el modelo no emitió tokens sueltos
                        hubo_tokens = False
                    elif isinstance(m, ToolMessage):
                        yield _sse("resultado", {"texto": _texto(m.content)})
    except Exception as e:  # noqa: BLE001 — un turno fallido no debe cortar la conexión sin avisar
        yield _sse("error", {"mensaje": f"No pude completar la solicitud ({type(e).__name__}): {e}"})
        return
    proveedor = "—" if not modelo else modelo if modelo == principal else f"{modelo} ↩ fallback"
    yield _sse("fin", {"thread_id": thread_id, "proveedor": proveedor})


def crear_app(agente, db: Db, principal: str, respaldo: str, propias: list[str]) -> FastAPI:
    app = FastAPI(title="Agente de ventas")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(INDEX)

    @app.get("/api/modelo")
    def modelo():
        return {"principal": principal, "respaldo": respaldo, "herramientas": propias,
                "integradas": herramientas_integradas(agente, propias)}

    @app.get("/api/catalogo")
    def catalogo():
        return servicio.listar_catalogo(db)

    @app.get("/api/pedidos/{pedido_id}")
    def pedido(pedido_id: int):
        try:
            return servicio.obtener_pedido(db, pedido_id)
        except ErrorDeNegocio as e:
            raise HTTPException(404, str(e)) from None

    @app.post("/api/chat")
    def chat(req: Chat):
        # generador síncrono: Starlette lo corre en un hilo y no bloquea el event loop
        return StreamingResponse(_turno(agente, principal, req.thread_id or uuid.uuid4().hex, req.mensaje),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app


def main() -> None:
    try:
        settings = cargar()
        db = Db(settings.database_url, settings.database_url_ro)
    except ConfigError as e:
        raise SystemExit(f"Error de configuración: {e}") from None
    except PoolTimeout:
        raise SystemExit("No se pudo conectar a PostgreSQL. ¿Está levantado? (docker compose up -d --wait)") from None
    herramientas = construir_herramientas(db, settings.tasa_impuesto)
    nim, gemini = construir_modelos(settings)
    agente = construir_agente(nim, gemini, herramientas)
    app = crear_app(agente, db, settings.nim_model, settings.gemini_model, [h.name for h in herramientas])
    try:
        # shortcut: sin auth; loopback por defecto. El contenedor usa 0.0.0.0 y el compose publica solo en 127.0.0.1.
        # Para exponerlo a una red hace falta autenticación.
        uvicorn.run(app, host=os.environ.get("WEB_HOST", "127.0.0.1"), port=8000)
    finally:
        db.close()


if __name__ == "__main__":
    main()
