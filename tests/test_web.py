import json

import pytest
from fastapi.testclient import TestClient

from tests.fakes import Boom, guion, ia, llamada
from ventas.agent import construir_agente
from ventas.tools import construir_herramientas
from ventas.web.app import crear_app


@pytest.fixture
def cliente(db, datos, tasa):
    def _armar(*mensajes):
        herramientas = construir_herramientas(db, tasa)
        agente = construir_agente(guion(cls=Boom), [guion(*mensajes)], herramientas)
        app = crear_app(agente, db, "gemini-x", "nim-x", [h.name for h in herramientas])
        return TestClient(app)
    return _armar


def _eventos(resp) -> list[tuple[str, dict]]:
    out = []
    for bloque in resp.text.strip().split("\n\n"):
        ev, dato = bloque.split("\n", 1)
        out.append((ev.removeprefix("event: "), json.loads(dato.removeprefix("data: "))))
    return out


def test_chat_streamea_herramienta_tokens_y_fin(cliente):
    c = cliente(ia(tool_calls=[llamada("buscar_productos", texto="teclado")], modelo="nim-x"),
                ia("Tengo el Teclado mecánico", modelo="nim-x"))
    evs = _eventos(c.post("/api/chat", json={"mensaje": "busco un teclado"}))
    nombres = [e for e, _ in evs]
    assert nombres[0] == "herramienta" and evs[0][1]["nombre"] == "buscar_productos"
    assert "TEC-001" in evs[1][1]["texto"] and nombres[1] == "resultado"
    assert "".join(d["texto"] for e, d in evs if e == "token").strip() == "Tengo el Teclado mecánico"
    assert nombres.count("token") > 1  # llegó por trozos, no de golpe
    assert evs[-1][0] == "fin" and evs[-1][1]["proveedor"] == "nim-x ↩ fallback"


def test_chat_mantiene_la_conversacion_por_thread_id(cliente):
    c = cliente(ia("uno"), ia("dos"))
    tid = _eventos(c.post("/api/chat", json={"mensaje": "a"}))[-1][1]["thread_id"]
    fin = _eventos(c.post("/api/chat", json={"mensaje": "b", "thread_id": tid}))[-1]
    assert fin[1]["thread_id"] == tid


def test_chat_si_fallan_ambos_proveedores_emite_error(db, datos, tasa):
    herramientas = construir_herramientas(db, tasa)
    agente = construir_agente(guion(cls=Boom), [guion(cls=Boom)], herramientas)
    c = TestClient(crear_app(agente, db, "gemini-x", "nim-x", []))
    evs = _eventos(c.post("/api/chat", json={"mensaje": "hola"}))
    assert [e for e, _ in evs] == ["error"] and "No pude completar" in evs[0][1]["mensaje"]


def test_chat_rechaza_mensaje_vacio(cliente):
    assert cliente().post("/api/chat", json={"mensaje": ""}).status_code == 422


def test_catalogo_modelo_y_pedido(cliente):
    c = cliente()
    assert {f["sku"] for f in c.get("/api/catalogo").json()} == {"TEC-001", "MOU-001", "RAR-001"}
    m = c.get("/api/modelo").json()
    assert m["principal"] == "gemini-x" and "write_todos" in m["integradas"]
    assert c.get("/api/pedidos/999").status_code == 404
    assert "<title>" in c.get("/").text
