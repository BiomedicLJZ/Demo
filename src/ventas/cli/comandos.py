"""Definición de comandos slash, parseo y autocompletado."""
from dataclasses import dataclass

from prompt_toolkit.completion import Completer, Completion


@dataclass(frozen=True)
class Comando:
    nombre: str  # sin "/"
    descripcion: str


COMANDOS = (
    Comando("ayuda", "Muestra esta ayuda"),
    Comando("nuevo", "Inicia una conversación nueva"),
    Comando("modelo", "Muestra el proveedor de IA activo"),
    Comando("herramientas", "Lista las herramientas del agente"),
    Comando("todos", "Muestra el plan actual del agente"),
    Comando("catalogo", "Muestra el catálogo con stock"),
    Comando("pedido", "Muestra un pedido: /pedido <id>"),
    Comando("limpiar", "Limpia la pantalla"),
    Comando("salir", "Cierra el programa"),
)


def parsear(linea: str) -> tuple[str, list[str]] | None:
    linea = linea.strip()
    if not linea.startswith("/"):
        return None
    partes = linea[1:].split()
    return (partes[0].lower(), partes[1:]) if partes else ("", [])


class CompletadorSlash(Completer):
    """Sugiere comandos al escribir `/`; no completa argumentos ni texto normal."""

    def get_completions(self, document, complete_event):
        texto = document.text_before_cursor
        if not texto.startswith("/") or " " in texto:
            return
        prefijo = texto[1:].lower()
        for c in COMANDOS:
            if c.nombre.startswith(prefijo):
                yield Completion("/" + c.nombre, start_position=-len(texto), display_meta=c.descripcion)
