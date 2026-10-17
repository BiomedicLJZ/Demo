import json

import pytest
from langchain_core.messages import HumanMessage

from ventas.tools import construir_herramientas

NOMBRES = {"buscar_productos", "registrar_cliente", "cotizar", "crear_pedido",
           "registrar_pago", "emitir_comprobante", "consulta_sql"}


@pytest.fixture
def t(db, datos, tasa):
    return {h.name: h for h in construir_herramientas(db, tasa)}


def test_catalogo_de_herramientas(t):
    assert set(t) == NOMBRES
    assert all(h.description for h in t.values())
    assert all(h.handle_tool_error is True for h in t.values())


def test_el_llm_solo_manda_sku_y_cantidad(t):
    props = t["crear_pedido"].args_schema.model_json_schema()
    assert "precio" not in json.dumps(props).lower()


def hablar(texto):
    """Estado que el grafo inyecta en las herramientas: el último mensaje humano es lo que dijo el cliente."""
    return {"messages": [HumanMessage(texto)]}


def test_flujo_completo_de_venta(t):
    cli = json.loads(t["registrar_cliente"].invoke({"nombre": "Luis", "email": "luis@example.com"}))
    items = [{"sku": "TEC-001", "cantidad": 1}]
    assert json.loads(t["cotizar"].invoke({"items": items}))["total"] == "1160.00"
    ped = json.loads(t["crear_pedido"].invoke({"cliente_id": cli["id"], "items": items, "state": hablar("Sí, confirmo")}))
    pago = json.loads(t["registrar_pago"].invoke({"pedido_id": ped["pedido_id"], "monto": 1160.0, "metodo": "tarjeta",
                                                  "state": hablar("pago con Tarjeta")}))
    assert pago["estado"] == "pagado"
    comp = json.loads(t["emitir_comprobante"].invoke({"pedido_id": ped["pedido_id"]}))
    assert comp["numero"] == "COMP-000001"


def test_error_de_negocio_vuelve_como_texto(t):
    out = t["crear_pedido"].invoke({"cliente_id": 1, "items": [{"sku": "TEC-001", "cantidad": 99}],
                                    "state": hablar("sí")})
    assert "Stock insuficiente" in out


def test_buscar_productos_devuelve_json(t):
    filas = json.loads(t["buscar_productos"].invoke({"texto": "mouse"}))
    assert filas[0]["sku"] == "MOU-001" and filas[0]["precio"] == "200.50"


def test_consulta_sql_devuelve_filas(t):
    r = json.loads(t["consulta_sql"].invoke({"sql": "SELECT count(*) AS n FROM productos"}))
    assert r["filas"] == [{"n": 4}] and r["truncado"] is False


def test_consulta_sql_rechaza_escritura_como_texto(t):
    assert "SELECT" in t["consulta_sql"].invoke({"sql": "DELETE FROM productos"})


@pytest.mark.parametrize("texto", ["Soy Ana, mi email es ana@example.com", "no, todavía no confirmo", "¿cuánto cuesta?", ""])
def test_crear_pedido_exige_confirmacion_del_cliente(t, texto):
    out = t["crear_pedido"].invoke({"cliente_id": 1, "items": [{"sku": "TEC-001", "cantidad": 1}],
                                    "state": hablar(texto)})
    assert "no ha confirmado" in out
    assert t["consulta_sql"].invoke({"sql": "SELECT count(*) AS n FROM pedidos"}).count('"n": 0') == 1


def test_registrar_pago_exige_el_metodo_dicho_por_el_cliente(t):
    ped = json.loads(t["crear_pedido"].invoke({"cliente_id": 1, "items": [{"sku": "TEC-001", "cantidad": 1}],
                                               "state": hablar("sí")}))
    for texto in ["Soy Ana", "pago en efectivo"]:  # sin método / método distinto al del LLM
        out = t["registrar_pago"].invoke({"pedido_id": ped["pedido_id"], "monto": 1160.0, "metodo": "tarjeta",
                                          "state": hablar(texto)})
        assert "no ha indicado ese método" in out
    assert "pendiente_pago" in t["consulta_sql"].invoke({"sql": "SELECT estado FROM pedidos"})
