"""Modelos falsos para probar el agente sin red."""
from itertools import chain

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk


class Fake(GenericFakeChatModel):
    """Acepta bind_tools (el agente siempre lo llama)."""

    def bind_tools(self, tools, **kwargs):
        return self

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        # el stream del fake parte el texto en palabras y no emite nada si el contenido está vacío (tool calls)
        siguiente = next(self.messages)
        if siguiente.tool_calls or not siguiente.content:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content=siguiente.content, tool_calls=siguiente.tool_calls,
                response_metadata=siguiente.response_metadata))
            return
        self.messages = chain([siguiente], self.messages)  # lo devolvemos para que el stream normal lo parta
        yield from super()._stream(messages, stop, run_manager, **kwargs)


class Boom(Fake):
    """Falla siempre, como un NIM caído."""

    def _generate(self, *args, **kwargs):
        raise RuntimeError("nim caído")

    _stream = _generate  # el modo streaming no pasa por _generate


def ia(contenido: str = "", tool_calls: list | None = None, modelo: str = "gemini-x") -> AIMessage:
    return AIMessage(content=contenido, tool_calls=tool_calls or [],
                     response_metadata={"model_name": modelo})


_n = 0


def llamada(herramienta: str, /, **args) -> dict:
    # posicional-only: una herramienta puede tener un argumento llamado `nombre`
    global _n
    _n += 1
    return {"name": herramienta, "args": args, "id": f"call-{_n}"}


def guion(*mensajes: AIMessage, cls=Fake):
    return cls(messages=iter(mensajes))
