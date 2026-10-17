from decimal import Decimal

import pytest

from ventas import servicio
from ventas.servicio import ErrorDeNegocio

ANA = 1


@pytest.fixture
def pedido(db, datos, tasa):
    """Pedido pendiente de pago: 1 teclado = 1000.00 + 160.00 = 1160.00."""
    return servicio.crear_pedido(db, ANA, [{"sku": "TEC-001", "cantidad": 1}], tasa)["pedido_id"]


def _estado(db, pid):
    with db.ro.connection() as c:
        return c.execute("SELECT estado FROM pedidos WHERE id = %s", (pid,)).fetchone()["estado"]


def test_pago_exitoso(db, pedido):
    r = servicio.registrar_pago(db, pedido, Decimal("1160.00"), "Tarjeta")
    assert r["estado"] == "pagado" and r["metodo"] == "tarjeta" and r["referencia"].startswith("SIM-")
    assert _estado(db, pedido) == "pagado"


@pytest.mark.parametrize("monto", [1160.0, "1160.00", 1160, Decimal("1160")])
def test_pago_acepta_float_texto_y_entero(db, pedido, monto):
    assert servicio.registrar_pago(db, pedido, monto, "efectivo")["monto"] == Decimal("1160.00")


def test_pago_monto_incorrecto(db, pedido):
    with pytest.raises(ErrorDeNegocio, match="no coincide"):
        servicio.registrar_pago(db, pedido, Decimal("1000.00"), "tarjeta")
    assert _estado(db, pedido) == "pendiente_pago"


def test_pago_doble(db, pedido):
    servicio.registrar_pago(db, pedido, Decimal("1160.00"), "tarjeta")
    with pytest.raises(ErrorDeNegocio, match="ya está pagado"):
        servicio.registrar_pago(db, pedido, Decimal("1160.00"), "tarjeta")


def test_pago_pedido_inexistente(db, datos):
    with pytest.raises(ErrorDeNegocio, match="No existe el pedido 999"):
        servicio.registrar_pago(db, 999, Decimal("1.00"), "tarjeta")


def test_pago_metodo_invalido(db, pedido):
    with pytest.raises(ErrorDeNegocio, match="Método de pago"):
        servicio.registrar_pago(db, pedido, Decimal("1160.00"), "bitcoin")


def test_comprobante_requiere_pago(db, pedido):
    with pytest.raises(ErrorDeNegocio, match="no está pagado"):
        servicio.emitir_comprobante(db, pedido)


def test_comprobante_numero_y_idempotencia(db, datos, tasa):
    ids = []
    for _ in range(2):
        pid = servicio.crear_pedido(db, ANA, [{"sku": "MOU-001", "cantidad": 1}], tasa)["pedido_id"]
        servicio.registrar_pago(db, pid, Decimal("232.58"), "tarjeta")
        ids.append(pid)
    a = servicio.emitir_comprobante(db, ids[0])
    a_otra_vez = servicio.emitir_comprobante(db, ids[0])
    b = servicio.emitir_comprobante(db, ids[1])
    assert a["numero"] == "COMP-000001" and a_otra_vez["numero"] == "COMP-000001"
    assert b["numero"] == "COMP-000002"  # la repetición no consumió la secuencia


def test_comprobante_pedido_inexistente(db, datos):
    with pytest.raises(ErrorDeNegocio, match="No existe el pedido 999"):
        servicio.emitir_comprobante(db, 999)


def test_obtener_pedido_completo(db, pedido):
    servicio.registrar_pago(db, pedido, Decimal("1160.00"), "tarjeta")
    servicio.emitir_comprobante(db, pedido)
    p = servicio.obtener_pedido(db, pedido)
    assert p["cliente"] == "Ana Pérez" and p["estado"] == "pagado" and p["total"] == Decimal("1160.00")
    assert p["items"][0]["sku"] == "TEC-001" and p["pago"]["metodo"] == "tarjeta"
    assert p["comprobante"]["numero"] == "COMP-000001"


def test_obtener_pedido_sin_pago(db, pedido):
    p = servicio.obtener_pedido(db, pedido)
    assert p["pago"] is None and p["comprobante"] is None


def test_obtener_pedido_inexistente(db, datos):
    with pytest.raises(ErrorDeNegocio, match="No existe el pedido 999"):
        servicio.obtener_pedido(db, 999)
