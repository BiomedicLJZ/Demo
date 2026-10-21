"""API REST + UI web mínima. El chat responde por SSE: tokens a medida que el modelo escribe."""
import json
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, Field

from ventas import servicio
from ventas.agent import construir_agente, herramientas_integradas
from ventas.cli.app import _texto
from ventas.config import ConfigError, cargar
from ventas.db import Db
from ventas.empresas import EMPRESAS, Empresa, abrir_db
from ventas.models import construir_modelos
from ventas.servicio import ErrorDeNegocio
from ventas.tools import construir_herramientas
from ventas.usuarios import SESION_SEGUNDOS, Usuarios

INDEX = Path(__file__).with_name("index.html")
COOKIE = "sesion"


@dataclass
class Contexto:
    """Lo que hace falta para atender a una empresa: su BD y su agente (con su propio historial de conversaciones)."""
    empresa: Empresa
    db: Db
    agente: object
    propias: list[str]


class Login(BaseModel):
    usuario: str = Field(max_length=100)
    clave: str = Field(max_length=200)


class Chat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None  # sin él se abre una conversación nueva; se devuelve en `fin`


def _sse(evento: str, datos: dict) -> str:
    return f"event: {evento}\ndata: {json.dumps(datos, ensure_ascii=False, default=str)}\n\n"


def _turno(agente, principal: str, usuario: str, thread_id: str, texto: str):
    config = {"configurable": {"thread_id": f"{usuario}:{thread_id}"}}  # el hilo es de quien lo abrió
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


def crear_app(contexto_de: Callable[[str], Contexto], usuarios: Usuarios, principal: str, respaldo: str) -> FastAPI:
    app = FastAPI(title="Agente de ventas")

    def actual(request: Request) -> tuple[str, Contexto]:
        """Usuario y contexto de su empresa. La empresa sale de la sesión, nunca de la petición."""
        s = usuarios.sesion(request.cookies.get(COOKIE, ""))
        if not s:
            raise HTTPException(401, "Inicia sesión.")
        return s[0], _contexto(s[1])

    def _contexto(empresa: str) -> Contexto:
        try:
            return contexto_de(empresa)
        except KeyError:
            raise HTTPException(401, "Inicia sesión.") from None
        except ConfigError as e:
            raise HTTPException(503, str(e)) from None
        except PoolTimeout:
            raise HTTPException(503, "No se pudo conectar a PostgreSQL. ¿Está levantado? (docker compose up -d --wait)") from None

    def _perfil(usuario: str, ctx: Contexto) -> dict:
        return {"usuario": usuario, "empresa": ctx.empresa.nombre, "sugerencias": ctx.empresa.sugerencias}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(INDEX)

    @app.get("/api/salud")
    def salud():
        return {"ok": True}

    @app.post("/api/login")
    def login(req: Login, response: Response):
        v = usuarios.verificar(req.usuario, req.clave)
        if not v:
            raise HTTPException(401, "Usuario o contraseña incorrectos.")
        ctx = _contexto(v[1])  # si su BD no existe, se avisa aquí y no a mitad de la conversación
        response.set_cookie(COOKIE, usuarios.abrir_sesion(*v), max_age=SESION_SEGUNDOS, httponly=True, samesite="strict")
        return _perfil(v[0], ctx)

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        usuarios.cerrar_sesion(request.cookies.get(COOKIE, ""))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/yo")
    def yo(sesion: tuple[str, Contexto] = Depends(actual)):
        return _perfil(*sesion)

    @app.get("/api/modelo")
    def modelo(sesion: tuple[str, Contexto] = Depends(actual)):
        ctx = sesion[1]
        return {"principal": principal, "respaldo": respaldo, "herramientas": ctx.propias,
                "integradas": herramientas_integradas(ctx.agente, ctx.propias)}

    @app.get("/api/catalogo")
    def catalogo(sesion: tuple[str, Contexto] = Depends(actual)):
        return servicio.listar_catalogo(sesion[1].db)

    @app.get("/api/pedidos/{pedido_id}")
    def pedido(pedido_id: int, sesion: tuple[str, Contexto] = Depends(actual)):
        try:
            return servicio.obtener_pedido(sesion[1].db, pedido_id)
        except ErrorDeNegocio as e:
            raise HTTPException(404, str(e)) from None

    @app.post("/api/chat")
    def chat(req: Chat, sesion: tuple[str, Contexto] = Depends(actual)):
        usuario, ctx = sesion
        # generador síncrono: Starlette lo corre en un hilo y no bloquea el event loop
        return StreamingResponse(_turno(ctx.agente, principal, usuario, req.thread_id or uuid.uuid4().hex, req.mensaje),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app


def main() -> None:
    try:
        settings = cargar()
    except ConfigError as e:
        raise SystemExit(f"Error de configuración: {e}") from None
    bedrock, nim, gemini = construir_modelos(settings)  # un solo juego de clientes, compartido por todos los agentes
    usuarios = Usuarios(os.environ.get("AUTH_DB", "auth.db"))
    contextos: dict[str, Contexto] = {}
    candado = threading.Lock()

    def contexto_de(id: str) -> Contexto:
        """Abre la BD y el agente de la empresa la primera vez que alguien entra. KeyError si no existe."""
        with candado:
            if id not in contextos:
                e = EMPRESAS[id]
                db = abrir_db(e, settings)
                herramientas = construir_herramientas(db, settings.tasa_impuesto)
                agente = construir_agente(bedrock, [nim, gemini], herramientas, e.negocio)
                contextos[id] = Contexto(e, db, agente, [h.name for h in herramientas])
            return contextos[id]

    app = crear_app(contexto_de, usuarios, settings.bedrock_model, f"{settings.nim_model}, {settings.gemini_model}")
    try:
        # shortcut: HTTP sin TLS (cookie sin Secure); loopback por defecto. El contenedor usa 0.0.0.0 y el compose publica
        # solo en 127.0.0.1. Para exponerlo a una red hace falta HTTPS (y cookie Secure).
        uvicorn.run(app, host=os.environ.get("WEB_HOST", "127.0.0.1"), port=int(os.environ.get("WEB_PORT", "8000")))
    finally:
        for c in contextos.values():
            c.db.close()


if __name__ == "__main__":
    main()
