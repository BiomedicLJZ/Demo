"""Loop del CLI: lee una línea, la despacha a un comando slash o al agente."""
import argparse
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, ToolMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from psycopg_pool import PoolTimeout
from rich.console import Console

from ventas import servicio
from ventas.agent import construir_agente, herramientas_integradas
from ventas.cli import render
from ventas.cli.comandos import CompletadorSlash, parsear
from ventas.config import ConfigError, cargar
from ventas.db import Db
from ventas.empresas import EMPRESAS, abrir_db
from ventas.models import construir_modelos
from ventas.servicio import ErrorDeNegocio
from ventas.tools import construir_herramientas


@dataclass
class Sesion:
    agente: object
    db: Db
    console: Console
    bedrock_model: str
    nim_model: str
    gemini_model: str
    propias: list[str]
    integradas: list[str]
    thread_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    proveedor: str = "—"

    @property
    def config(self) -> dict:
        return {"configurable": {"thread_id": self.thread_id}}


def etiqueta_proveedor(nombre_modelo: str | None, bedrock_model: str, nim_model: str) -> str:
    if not nombre_modelo:
        return "—"
    if nombre_modelo == bedrock_model:
        return "Bedrock"
    return "NIM ↩ fallback" if nombre_modelo == nim_model else "Gemini ↩ fallback"


def _texto(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in contenido)


def ejecutar_turno(s: Sesion, texto: str) -> None:
    final, modelo = None, None
    with s.console.status("Pensando…", spinner="dots"):
        for chunk in s.agente.stream({"messages": [("user", texto)]}, s.config, stream_mode="updates"):
            for nodo, upd in chunk.items():
                if nodo not in ("model", "tools") or not isinstance(upd, dict):
                    continue  # otros nodos (middleware) pueden reemitir el historial entero
                msgs = upd.get("messages", [])
                for m in msgs if isinstance(msgs, list) else [msgs]:
                    if isinstance(m, AIMessage):
                        for tc in m.tool_calls:
                            s.console.print(render.linea_herramienta(tc["name"], tc["args"]))
                        modelo = m.response_metadata.get("model_name", modelo)
                        if not m.tool_calls:
                            final = _texto(m.content)
                    elif isinstance(m, ToolMessage):
                        s.console.print(render.resultado_herramienta(_texto(m.content)))
    s.proveedor = etiqueta_proveedor(modelo, s.bedrock_model, s.nim_model)
    if final:
        s.console.print(render.respuesta(final, s.proveedor))


def _ayuda(s, args):
    s.console.print(render.tabla_ayuda())


def _nuevo(s, args):
    s.thread_id = uuid.uuid4().hex
    s.console.print("[green]Conversación nueva.[/]")


def _modelo(s, args):
    s.console.print(f"Principal: [bold]{s.bedrock_model}[/] (Bedrock)  ·  Respaldo: [bold]{s.nim_model}[/] (NIM), "
                    f"[bold]{s.gemini_model}[/] (Gemini)  ·  "
                    f"Último en responder: [bold]{s.proveedor}[/]")


def _herramientas(s, args):
    s.console.print(render.tabla_herramientas(s.propias, s.integradas))


def _todos(s, args):
    todos = s.agente.get_state(s.config).values.get("todos") or []
    s.console.print(render.tabla_todos(todos) if todos else "El agente no tiene un plan activo.")


def _catalogo(s, args):
    s.console.print(render.tabla_catalogo(servicio.listar_catalogo(s.db)))


def _pedido(s, args):
    if len(args) != 1 or not args[0].isdigit():
        s.console.print(render.error("Uso: /pedido <id>"))
        return
    s.console.print(render.tabla_pedido(servicio.obtener_pedido(s.db, int(args[0]))))


def _limpiar(s, args):
    s.console.clear()


_MANEJADORES = {"ayuda": _ayuda, "nuevo": _nuevo, "modelo": _modelo, "herramientas": _herramientas,
                "todos": _todos, "catalogo": _catalogo, "pedido": _pedido, "limpiar": _limpiar}


def procesar_linea(s: Sesion, linea: str) -> bool:
    """False = salir. Nunca lanza: los errores se muestran y la sesión sigue."""
    linea = linea.strip()
    if not linea:
        return True
    cmd = parsear(linea)
    try:
        if cmd is None:
            ejecutar_turno(s, linea)
        elif cmd[0] == "salir":
            return False
        elif cmd[0] in _MANEJADORES:
            _MANEJADORES[cmd[0]](s, cmd[1])
        else:
            s.console.print(render.error(f"Comando desconocido: /{cmd[0]}. Escribe /ayuda."))
    except ErrorDeNegocio as e:
        s.console.print(render.error(str(e)))
    except KeyboardInterrupt:  # Ctrl-C cancela el turno en curso, no la sesión
        s.console.print(render.error("Turno cancelado."))
    except Exception as e:  # noqa: BLE001 — el loop del CLI no debe morir por un turno fallido
        s.console.print(render.error(f"No pude completar la solicitud ({type(e).__name__}): {e}"))
    return True


def main() -> None:
    ap = argparse.ArgumentParser(prog="ventas", description="Vendedor conversacional en la terminal.")
    ap.add_argument("--empresa", choices=list(EMPRESAS), default="agro", help="empresa a atender (por defecto agro)")
    empresa = EMPRESAS[ap.parse_args().empresa]  # shortcut: el CLI es local y no pide login; el aislamiento lo da la BD de la empresa
    console = Console()
    try:
        settings = cargar()
        db = abrir_db(empresa, settings)
    except ConfigError as e:
        console.print(render.error(str(e)))
        raise SystemExit(2) from None
    except PoolTimeout:
        console.print(render.error("No se pudo conectar a PostgreSQL. ¿Está levantado? (docker compose up -d --wait)"))
        raise SystemExit(2) from None

    herramientas = construir_herramientas(db, settings.tasa_impuesto)
    bedrock, nim, gemini = construir_modelos(settings)
    agente = construir_agente(bedrock, [nim, gemini], herramientas, empresa.negocio)
    propias = [h.name for h in herramientas]
    sesion = Sesion(agente=agente, db=db, console=console, bedrock_model=settings.bedrock_model, nim_model=settings.nim_model,
                    gemini_model=settings.gemini_model, propias=propias,
                    integradas=herramientas_integradas(agente, propias))

    console.print(f"Empresa: [bold]{empresa.nombre}[/]")
    console.print(render.banner(settings.bedrock_model, settings.nim_model, settings.gemini_model))
    prompt = PromptSession(completer=CompletadorSlash(), complete_while_typing=True)
    try:
        while True:
            try:
                linea = prompt.prompt(HTML("<b><ansigreen>tú › </ansigreen></b>"))
            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            if not procesar_linea(sesion, linea):
                break
    finally:
        db.close()
    console.print("Hasta luego.")


if __name__ == "__main__":
    main()
