import pytest

from ventas import servicio
from ventas.servicio import ErrorDeNegocio


def test_buscar_ignora_acentos_y_mayusculas(db, datos):
    assert [p["sku"] for p in servicio.buscar_productos(db, "MECANICO")] == ["TEC-001"]


def test_buscar_por_sku(db, datos):
    assert [p["sku"] for p in servicio.buscar_productos(db, "mou-001")] == ["MOU-001"]


def test_buscar_plurales_palabras_sueltas_y_orden(db, datos):
    assert [p["sku"] for p in servicio.buscar_productos(db, "mouses")] == ["MOU-001"]
    assert [p["sku"] for p in servicio.buscar_productos(db, "teclado de mecánico")] == ["TEC-001"]
    assert [p["sku"] for p in servicio.buscar_productos(db, "mecánico teclado")] == ["TEC-001"]
    assert servicio.buscar_productos(db, "teclado inexistente") == []
    assert servicio.buscar_productos(db, "de") == []  # solo palabras vacías: busca el texto literal


def test_buscar_ignora_inactivos(db, datos):
    assert servicio.buscar_productos(db, "descontinuado") == []


def test_buscar_comodines_son_literales(db, datos):
    assert servicio.buscar_productos(db, "%") == []
    assert servicio.buscar_productos(db, "_") == []


def test_buscar_texto_vacio(db, datos):
    with pytest.raises(ErrorDeNegocio, match="buscar"):
        servicio.buscar_productos(db, "   ")


def test_buscar_devuelve_precio_y_stock(db, datos):
    p = servicio.buscar_productos(db, "mouse")[0]
    assert str(p["precio"]) == "200.50" and p["stock"] == 10


def test_listar_catalogo_solo_activos_ordenado(db, datos):
    nombres = [p["nombre"] for p in servicio.listar_catalogo(db)]
    assert nombres == sorted(nombres) and "Producto descontinuado" not in nombres and len(nombres) == 3


def test_registrar_cliente_nuevo_y_repetido(db, datos):
    a = servicio.registrar_cliente(db, "Luis", " Luis@Example.com ")
    b = servicio.registrar_cliente(db, "Otro nombre", "luis@example.com")
    assert a["nuevo"] is True and b["nuevo"] is False
    assert a["id"] == b["id"] and a["email"] == "luis@example.com" and b["nombre"] == "Luis"


@pytest.mark.parametrize("email", ["", "sin-arroba", "a@b", "a b@c.com"])
def test_registrar_cliente_email_invalido(db, datos, email):
    with pytest.raises(ErrorDeNegocio, match="email"):
        servicio.registrar_cliente(db, "Luis", email)


def test_registrar_cliente_sin_nombre(db, datos):
    with pytest.raises(ErrorDeNegocio, match="nombre"):
        servicio.registrar_cliente(db, "  ", "x@y.com")
