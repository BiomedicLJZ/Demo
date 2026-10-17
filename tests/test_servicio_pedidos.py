from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from ventas import servicio
from ventas.servicio import ErrorDeNegocio

ANA = 1


def _stock(db, sku):
    with db.ro.connection() as c:
        return c.execute("SELECT stock FROM productos WHERE sku = %s", (sku,)).fetchone()["stock"]


def _n(db, tabla):
    with db.ro.connection() as c:
        return c.execute(f"SELECT count(*) AS n FROM {tabla}").fetchone()["n"]


def test_cotizar_calcula_totales(db, datos, tasa):
    c = servicio.cotizar(db, [{"sku": "TEC-001", "cantidad": 2}, {"sku": "MOU-001", "cantidad": 1}], tasa)
    assert c["subtotal"] == Decimal("2200.50")
    assert c["impuesto"] == Decimal("352.08")
    assert c["total"] == Decimal("2552.58")
    assert [l["sku"] for l in c["lineas"]] == ["TEC-001", "MOU-001"]


def test_cotizar_usa_la_tasa_de_cada_producto(db, datos, tasa):
    with db.rw.connection() as c:
        c.execute("UPDATE productos SET impuesto = 0 WHERE sku = 'MOU-001'")
        c.execute("UPDATE productos SET impuesto = 0.06 WHERE sku = 'RAR-001'")
    c = servicio.cotizar(db, [{"sku": "TEC-001", "cantidad": 1}, {"sku": "MOU-001", "cantidad": 1},
                              {"sku": "RAR-001", "cantidad": 1}], tasa)
    assert c["impuesto"] == Decimal("190.00")  # 1000*0.16 (global, impuesto NULL) + 200.50*0 + 500*0.06
    assert c["total"] == c["subtotal"] + c["impuesto"]


def test_items_repetidos_se_suman_y_validan_stock(db, datos, tasa):
    c = servicio.cotizar(db, [{"sku": "tec-001", "cantidad": 1}, {"sku": "TEC-001", "cantidad": 2}], tasa)
    assert len(c["lineas"]) == 1 and c["lineas"][0]["cantidad"] == 3
    with pytest.raises(ErrorDeNegocio, match="Stock insuficiente"):
        servicio.cotizar(db, [{"sku": "RAR-001", "cantidad": 1}, {"sku": "RAR-001", "cantidad": 1}], tasa)


@pytest.mark.parametrize("cantidad", [0, -1, 1.5, True, "2", None])
def test_cantidad_invalida_se_rechaza(db, datos, tasa, cantidad):
    with pytest.raises(ErrorDeNegocio, match="Cantidad inválida"):
        servicio.cotizar(db, [{"sku": "TEC-001", "cantidad": cantidad}], tasa)


def test_items_vacios(db, datos, tasa):
    with pytest.raises(ErrorDeNegocio, match="no tiene productos"):
        servicio.cotizar(db, [], tasa)


def test_sku_inexistente_o_inactivo(db, datos, tasa):
    with pytest.raises(ErrorDeNegocio, match="OLD-001"):
        servicio.cotizar(db, [{"sku": "OLD-001", "cantidad": 1}], tasa)
    with pytest.raises(ErrorDeNegocio, match="NOPE-9"):
        servicio.cotizar(db, [{"sku": "NOPE-9", "cantidad": 1}], tasa)


def test_stock_insuficiente_menciona_lo_disponible(db, datos, tasa):
    with pytest.raises(ErrorDeNegocio, match=r"pediste 6, hay 5"):
        servicio.cotizar(db, [{"sku": "TEC-001", "cantidad": 6}], tasa)


def test_producto_agotado_aparece_pero_no_se_vende(db, datos, tasa):
    servicio.crear_pedido(db, ANA, [{"sku": "RAR-001", "cantidad": 1}], tasa)
    assert servicio.buscar_productos(db, "limitada")[0]["stock"] == 0
    with pytest.raises(ErrorDeNegocio, match="hay 0"):
        servicio.cotizar(db, [{"sku": "RAR-001", "cantidad": 1}], tasa)


def test_crear_pedido_descuenta_stock(db, datos, tasa):
    p = servicio.crear_pedido(db, ANA, [{"sku": "TEC-001", "cantidad": 2}], tasa)
    assert p["estado"] == "pendiente_pago" and p["total"] == Decimal("2320.00")
    assert _stock(db, "TEC-001") == 3
    assert _n(db, "pedido_items") == 1


def test_crear_pedido_es_atomico(db, datos, tasa):
    with pytest.raises(ErrorDeNegocio):
        servicio.crear_pedido(db, ANA, [{"sku": "MOU-001", "cantidad": 1}, {"sku": "TEC-001", "cantidad": 6}], tasa)
    assert _stock(db, "MOU-001") == 10 and _n(db, "pedidos") == 0


def test_crear_pedido_cliente_inexistente(db, datos, tasa):
    with pytest.raises(ErrorDeNegocio, match="cliente 999"):
        servicio.crear_pedido(db, 999, [{"sku": "TEC-001", "cantidad": 1}], tasa)


def test_sin_sobreventa_con_compras_simultaneas(db, datos, tasa):
    def comprar(_):
        try:
            servicio.crear_pedido(db, ANA, [{"sku": "RAR-001", "cantidad": 1}], tasa)
            return "ok"
        except ErrorDeNegocio:
            return "sin_stock"

    with ThreadPoolExecutor(max_workers=4) as ex:
        resultados = list(ex.map(comprar, range(4)))
    assert resultados.count("ok") == 1 and resultados.count("sin_stock") == 3
    assert _stock(db, "RAR-001") == 0 and _n(db, "pedidos") == 1
