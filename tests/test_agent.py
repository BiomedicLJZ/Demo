import pytest
from langchain_core.tools import tool

from tests.fakes import Boom, guion, ia, llamada
from ventas.agent import construir_agente, herramientas_integradas

CFG = {"configurable": {"thread_id": "t1"}}


@tool
def saluda(nombre: str) -> str:
    """Saluda."""
    return f"hola {nombre}"


def test_el_fallback_responde_cuando_nim_falla():
    agente = construir_agente(
        guion(cls=Boom),
        guion(ia(tool_calls=[llamada("saluda", nombre="Ana")]), ia("listo")),
        [saluda],
    )
    r = agente.invoke({"messages": [("user", "hola")]}, CFG)
    ultimo = r["messages"][-1]
    assert ultimo.content == "listo" and ultimo.response_metadata["model_name"] == "gemini-x"
    assert any(m.content == "hola Ana" for m in r["messages"])


def test_si_fallan_ambos_se_propaga_el_error():
    agente = construir_agente(guion(cls=Boom), guion(cls=Boom), [saluda])
    with pytest.raises(RuntimeError, match="nim caído"):
        agente.invoke({"messages": [("user", "hola")]}, {"configurable": {"thread_id": "t2"}})


def test_herramientas_integradas_incluye_todos_y_excluye_las_propias():
    agente = construir_agente(guion(cls=Boom), guion(), [saluda])
    integradas = herramientas_integradas(agente, ["saluda"])
    assert "write_todos" in integradas and "saluda" not in integradas
