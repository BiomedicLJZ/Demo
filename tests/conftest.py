import os
import sqlite3
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from ventas.db import Db

URL_RW = os.environ.get("TEST_DATABASE_URL", "postgresql://ventas_rw:ventas_rw@localhost:5433/ventas_test")
URL_RO = os.environ.get("TEST_DATABASE_URL_RO", "postgresql://ventas_ro:ventas_ro@localhost:5433/ventas_test")
URL_ADMIN = os.environ.get("TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5433/ventas_test")

# TEST_BACKEND=sqlite corre toda la suite contra un archivo SQLite temporal (sin Postgres ni Docker)
SQLITE = os.environ.get("TEST_BACKEND") == "sqlite"
solo_pg = pytest.mark.skipif(SQLITE, reason="comportamiento propio de PostgreSQL")
solo_sqlite = pytest.mark.skipif(not SQLITE, reason="comportamiento propio de SQLite")

PRODUCTOS = """INSERT INTO productos (sku, nombre, precio, stock, activo) VALUES
    ('TEC-001', 'Teclado mecánico', 1000.00, 5, true),
    ('MOU-001', 'Mouse óptico', 200.50, 10, true),
    ('OLD-001', 'Producto descontinuado', 50.00, 3, false),
    ('RAR-001', 'Edición limitada', 500.00, 1, true)"""
CLIENTE = "INSERT INTO clientes (nombre, email) VALUES ('Ana Pérez', 'ana@example.com')"


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    if SQLITE:
        ruta = tmp_path_factory.mktemp("sqlite") / "test.db"
        con = sqlite3.connect(ruta)
        con.executescript((Path(__file__).parent.parent / "db" / "schema_sqlite.sql").read_text())
        con.close()
        d = Db(f"sqlite:///{ruta}", f"sqlite:///{ruta}")
    else:
        try:
            d = Db(URL_RW, URL_RO)
        except PoolTimeout:
            pytest.exit("Postgres de pruebas no disponible. Ejecuta: docker compose up -d --wait", 2)
    yield d
    d.close()


@pytest.fixture
def datos(db):
    """BD de pruebas limpia con datos conocidos."""
    if SQLITE:  # sin AUTOINCREMENT, SQLite reinicia los ids desde 1 en tablas vacías
        with db.rw.connection() as c:
            for t in ("comprobantes", "pagos", "pedido_items", "pedidos", "productos", "clientes"):
                c.execute(f"DELETE FROM {t}")
            c.execute(PRODUCTOS)
            c.execute(CLIENTE)
        return
    with psycopg.connect(URL_ADMIN, autocommit=True) as c:
        assert c.info.dbname == "ventas_test", "nunca limpiar otra base"
        c.execute("TRUNCATE comprobantes, pagos, pedido_items, pedidos, productos, clientes RESTART IDENTITY CASCADE")
        c.execute("ALTER SEQUENCE comprobante_seq RESTART")
        c.execute(PRODUCTOS)
        c.execute(CLIENTE)


@pytest.fixture
def tasa() -> Decimal:
    return Decimal("0.16")


@pytest.fixture
def armar_sesion(db, datos, tasa):
    from rich.console import Console

    from tests.fakes import Boom, guion
    from ventas.agent import construir_agente, herramientas_integradas
    from ventas.cli.app import Sesion
    from ventas.tools import construir_herramientas

    def _armar(*mensajes, respaldo_falla=False):
        console = Console(record=True, width=110, force_terminal=False)
        herramientas = construir_herramientas(db, tasa)
        respaldo = guion(cls=Boom) if respaldo_falla else guion(*mensajes)
        agente = construir_agente(guion(cls=Boom), respaldo, herramientas)
        propias = [h.name for h in herramientas]
        s = Sesion(agente=agente, db=db, console=console, nim_model="nim-x", gemini_model="gemini-x",
                   propias=propias, integradas=herramientas_integradas(agente, propias))
        return s, console

    return _armar
