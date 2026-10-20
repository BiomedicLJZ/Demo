from datetime import datetime
from decimal import Decimal

from rich.console import Console

from ventas.cli import render


def _txt(obj) -> str:
    c = Console(record=True, width=110, force_terminal=False)
    c.print(obj)
    return c.export_text()


def test_banner_menciona_modelos():
    t = _txt(render.banner("bedrock-z", "nim-x", "gemini-y"))
    assert "bedrock-z" in t and "nim-x" in t and "gemini-y" in t and "/" in t


def test_tabla_catalogo():
    filas = [{"sku": "TEC-001", "nombre": "Teclado mecánico", "precio": Decimal("1299"), "stock": 0}]
    t = _txt(render.tabla_catalogo(filas))
    assert "TEC-001" in t and "1,299.00" in t and "Teclado mecánico" in t


def _pedido(**extra):
    return {"id": 7, "estado": "pagado", "cliente": "Ana Pérez", "email": "a@x.com",
            "subtotal": Decimal("1000.00"), "impuesto": Decimal("160.00"), "total": Decimal("1160.00"),
            "creado_en": datetime(2026, 10, 16),
            "items": [{"sku": "TEC-001", "nombre": "Teclado", "cantidad": 1, "precio_unitario": Decimal("1000.00")}],
            "pago": None, "comprobante": None, **extra}


def test_tabla_pedido_pendiente():
    t = _txt(render.tabla_pedido(_pedido(estado="pendiente_pago")))
    assert "Pedido #7" in t and "Ana Pérez" in t and "1,160.00" in t and "Pago:" not in t


def test_tabla_pedido_con_pago_y_comprobante():
    t = _txt(render.tabla_pedido(_pedido(
        pago={"monto": Decimal("1160.00"), "metodo": "tarjeta", "referencia": "SIM-AB12CD34", "pagado_en": None},
        comprobante={"numero": "COMP-000001", "emitido_en": None})))
    assert "SIM-AB12CD34" in t and "COMP-000001" in t


def test_linea_y_resultado_de_herramienta_truncan():
    assert "buscar_productos" in _txt(render.linea_herramienta("buscar_productos", {"texto": "x"}))
    largo = _txt(render.resultado_herramienta("a" * 500))
    assert len(largo.strip()) < 200 and "…" in largo


def test_respuesta_muestra_proveedor_y_markdown():
    t = _txt(render.respuesta("**Hola** cliente", "Gemini ↩ fallback"))
    assert "Hola" in t and "Gemini ↩ fallback" in t and "**" not in t


def test_respuesta_con_corchetes_no_rompe_rich():
    assert "[bold]" in _txt(render.respuesta("texto [bold] literal", "NIM"))


def test_tabla_todos():
    t = _txt(render.tabla_todos([{"content": "Cotizar", "status": "in_progress"},
                                 {"content": "Cobrar", "status": "pending"}]))
    assert "Cotizar" in t and "Cobrar" in t


def test_tabla_herramientas_y_ayuda():
    t = _txt(render.tabla_herramientas(["cotizar"], ["ls", "write_todos"]))
    assert "cotizar" in t and "write_todos" in t and "integrada" in t.lower()
    assert "/catalogo" in _txt(render.tabla_ayuda())


def test_error():
    assert "algo falló" in _txt(render.error("algo falló"))
