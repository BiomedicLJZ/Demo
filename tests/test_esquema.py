import psycopg
import pytest


def test_stock_no_puede_ser_negativo(db, datos):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.rw.connection() as c:
            c.execute("UPDATE productos SET stock = -1 WHERE sku = 'TEC-001'")


def test_rol_ro_no_puede_escribir(db, datos):
    with pytest.raises(psycopg.Error):
        with db.ro.connection() as c:
            c.execute("DELETE FROM productos")


def test_rol_ro_puede_leer(db, datos):
    with db.ro.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM productos").fetchone()["n"] == 4


def test_unaccent_disponible(db, datos):
    with db.ro.connection() as c:
        assert c.execute("SELECT unaccent('mecánico') AS u").fetchone()["u"] == "mecanico"
