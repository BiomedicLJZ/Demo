import pytest

from ventas import servicio
from ventas.servicio import ErrorDeNegocio


def _n_productos(db):
    with db.ro.connection() as c:
        return c.execute("SELECT count(*) AS n FROM productos").fetchone()["n"]


def test_select_simple(db, datos):
    r = servicio.consultar_sql(db, "SELECT sku FROM productos WHERE activo ORDER BY sku")
    assert [f["sku"] for f in r["filas"]] == ["MOU-001", "RAR-001", "TEC-001"] and r["truncado"] is False


def test_acepta_with_punto_y_coma_final_y_comentario(db, datos):
    assert servicio.consultar_sql(db, "WITH t AS (SELECT 1 AS x) SELECT x FROM t;")["filas"] == [{"x": 1}]
    assert servicio.consultar_sql(db, "SELECT 1 AS x -- comentario")["filas"] == [{"x": 1}]


@pytest.mark.parametrize("sql", [
    "INSERT INTO clientes (nombre, email) VALUES ('x', 'x@y.com')",
    "UPDATE productos SET stock = 0",
    "DELETE FROM productos",
    "DROP TABLE productos",
    "",
])
def test_rechaza_lo_que_no_es_select(db, datos, sql):
    with pytest.raises(ErrorDeNegocio, match="SELECT"):
        servicio.consultar_sql(db, sql)
    assert _n_productos(db) == 4


def test_rechaza_multiples_sentencias(db, datos):
    with pytest.raises(ErrorDeNegocio):
        servicio.consultar_sql(db, "SELECT 1; DROP TABLE productos")
    assert _n_productos(db) == 4


def test_rechaza_cte_que_modifica_datos(db, datos):
    with pytest.raises(ErrorDeNegocio):
        servicio.consultar_sql(db, "WITH x AS (DELETE FROM productos RETURNING *) SELECT * FROM x")
    assert _n_productos(db) == 4


def test_limita_a_200_filas(db, datos):
    r = servicio.consultar_sql(db, "SELECT generate_series(1, 500) AS n")
    assert len(r["filas"]) == 200 and r["truncado"] is True


def test_error_sql_se_explica(db, datos):
    with pytest.raises(ErrorDeNegocio, match="falló"):
        servicio.consultar_sql(db, "SELECT * FROM tabla_que_no_existe")


def test_timeout_de_5_segundos(db, datos):
    with pytest.raises(ErrorDeNegocio, match="falló"):
        servicio.consultar_sql(db, "SELECT pg_sleep(6)")


def test_set_config_no_saca_la_sesion_de_solo_lectura_ni_del_timeout(db, datos):
    # set_config(..., false) persiste en la conexión del pool: la consulta siguiente heredaba read-write y sin timeout
    import psycopg

    from tests.conftest import URL_ADMIN
    try:
        servicio.consultar_sql(
            db, "SELECT set_config('statement_timeout', '0', false), "
                "set_config('default_transaction_read_only', 'off', false)")
        with pytest.raises(ErrorDeNegocio, match="falló"):
            servicio.consultar_sql(db, "SELECT lo_create(0)")  # escribiría un large object
        with pytest.raises(ErrorDeNegocio, match="falló"):
            servicio.consultar_sql(db, "SELECT pg_sleep(6)")  # el timeout de 5 s debe seguir vigente
    finally:  # limpieza por si el defecto deja un large object en ventas_test
        with psycopg.connect(URL_ADMIN, autocommit=True) as c:
            c.execute("SELECT lo_unlink(oid) FROM pg_largeobject_metadata")
