import pytest

from tests.fakes import ia, llamada
from ventas import servicio
from ventas.cli.app import etiqueta_proveedor, procesar_linea


@pytest.mark.parametrize("nombre,esperado", [
    (None, "—"), ("bedrock-x", "Bedrock"), ("nim-x", "NIM ↩ fallback"), ("gemini-x", "Gemini ↩ fallback"),
])
def test_etiqueta_proveedor(nombre, esperado):
    assert etiqueta_proveedor(nombre, "bedrock-x", "nim-x") == esperado


def test_turno_con_fallback_muestra_herramienta_respuesta_y_proveedor(armar_sesion):
    s, console = armar_sesion(
        ia(tool_calls=[llamada("buscar_productos", texto="teclado")]),
        ia("Tengo el **Teclado mecánico** a 1,000.00"),
    )
    assert procesar_linea(s, "busco un teclado") is True
    out = console.export_text()
    assert "buscar_productos" in out and "TEC-001" in out       # línea de herramienta + resultado
    assert "Teclado mecánico" in out and "fallback" in out
    assert s.proveedor == "Gemini ↩ fallback"


def test_error_de_negocio_en_herramienta_no_tumba_el_turno(armar_sesion):
    s, console = armar_sesion(
        ia(tool_calls=[llamada("crear_pedido", cliente_id=1, items=[{"sku": "TEC-001", "cantidad": 99}])]),
        ia("Lo siento, no hay tanto stock."),
    )
    procesar_linea(s, "sí, confirmo 99 teclados")
    out = console.export_text()
    assert "Stock insuficiente" in out and "no hay tanto stock" in out


def test_el_grafo_inyecta_lo_que_dijo_el_cliente_y_bloquea_compra_sin_confirmar(armar_sesion, db):
    s, console = armar_sesion(
        ia(tool_calls=[llamada("crear_pedido", cliente_id=1, items=[{"sku": "TEC-001", "cantidad": 1}])]),
        ia("¿Confirmas la compra?"),
    )
    procesar_linea(s, "Soy Ana, mi email es ana@example.com")
    assert "no ha confirmado" in console.export_text()
    with db.ro.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM pedidos").fetchone()["n"] == 0


def test_si_fallan_ambos_proveedores_la_sesion_sigue(armar_sesion):
    s, console = armar_sesion(respaldo_falla=True)
    assert procesar_linea(s, "hola") is True
    assert "No pude completar" in console.export_text()


def test_contenido_en_bloques_se_aplana(armar_sesion):
    from langchain_core.messages import AIMessage
    msg = AIMessage(content=[{"type": "text", "text": "Hola en bloques"}], response_metadata={"model_name": "gemini-x"})
    s, console = armar_sesion(msg)
    procesar_linea(s, "hola")
    assert "Hola en bloques" in console.export_text()


def test_comandos_basicos(armar_sesion):
    s, console = armar_sesion()
    assert procesar_linea(s, "") is True
    assert procesar_linea(s, "/ayuda") is True
    assert procesar_linea(s, "/modelo") is True
    assert procesar_linea(s, "/herramientas") is True
    assert procesar_linea(s, "/limpiar") is True
    out = console.export_text()
    assert "/catalogo" in out and "bedrock-x" in out and "nim-x" in out and "gemini-x" in out
    assert "buscar_productos" in out and "write_todos" in out


def test_nuevo_cambia_el_hilo(armar_sesion):
    s, _ = armar_sesion()
    antes = s.thread_id
    procesar_linea(s, "/nuevo")
    assert s.thread_id != antes


def test_salir(armar_sesion):
    s, _ = armar_sesion()
    assert procesar_linea(s, "/salir") is False
    assert procesar_linea(s, "  /SALIR ") is False


def test_comando_desconocido_y_slash_solo(armar_sesion):
    s, console = armar_sesion()
    assert procesar_linea(s, "/foo") is True
    assert procesar_linea(s, "/") is True
    out = console.export_text()
    assert "desconocido" in out and "/ayuda" in out


def test_catalogo_sin_llm(armar_sesion):
    s, console = armar_sesion()
    procesar_linea(s, "/catalogo")
    out = console.export_text()
    assert "TEC-001" in out and "MOU-001" in out and "OLD-001" not in out


def test_pedido_existente_inexistente_y_uso(armar_sesion, db, tasa):
    pid = servicio.crear_pedido(db, 1, [{"sku": "TEC-001", "cantidad": 1}], tasa)["pedido_id"]
    s, console = armar_sesion()
    procesar_linea(s, f"/pedido {pid}")
    procesar_linea(s, "/pedido 999")
    procesar_linea(s, "/pedido abc")
    procesar_linea(s, "/pedido")
    out = console.export_text()
    assert f"Pedido #{pid}" in out and "No existe el pedido 999" in out and out.count("Uso: /pedido <id>") == 2


def test_todos_refleja_el_plan_del_agente(armar_sesion):
    s, console = armar_sesion(
        ia(tool_calls=[llamada("write_todos", todos=[{"content": "Cotizar teclado", "status": "in_progress"}])]),
        ia("Listo."),
    )
    procesar_linea(s, "ayúdame con una compra")
    procesar_linea(s, "/todos")
    assert "Cotizar teclado" in console.export_text()


def test_todos_sin_plan(armar_sesion):
    s, console = armar_sesion()
    procesar_linea(s, "/todos")
    assert "no tiene un plan" in console.export_text()


def test_ctrl_c_durante_un_turno_cancela_sin_cerrar_la_sesion(armar_sesion):
    class AgenteQueSeInterrumpe:
        def stream(self, *args, **kwargs):
            raise KeyboardInterrupt

    s, console = armar_sesion()
    s.agente = AgenteQueSeInterrumpe()
    assert procesar_linea(s, "hola") is True
    assert "cancelado" in console.export_text().lower()


def test_nuevo_hilo_no_hereda_el_plan(armar_sesion):
    s, console = armar_sesion(
        ia(tool_calls=[llamada("write_todos", todos=[{"content": "Tarea vieja", "status": "pending"}])]),
        ia("ok"),
    )
    procesar_linea(s, "hola")
    procesar_linea(s, "/nuevo")
    procesar_linea(s, "/todos")
    assert "no tiene un plan" in console.export_text().split("Conversación nueva")[-1]
