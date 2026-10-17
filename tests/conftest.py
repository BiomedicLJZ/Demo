import os
from decimal import Decimal

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from ventas.db import Db

URL_RW = os.environ.get("TEST_DATABASE_URL", "postgresql://ventas_rw:ventas_rw@localhost:5433/ventas_test")
URL_RO = os.environ.get("TEST_DATABASE_URL_RO", "postgresql://ventas_ro:ventas_ro@localhost:5433/ventas_test")
URL_ADMIN = os.environ.get("TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5433/ventas_test")


@pytest.fixture(scope="session")
def db():
    try:
        d = Db(URL_RW, URL_RO)
    except PoolTimeout:
        pytest.exit("Postgres de pruebas no disponible. Ejecuta: docker compose up -d --wait", 2)
    yield d
    d.close()


@pytest.fixture
def datos(db):
    """BD de pruebas limpia con datos conocidos."""
    with psycopg.connect(URL_ADMIN, autocommit=True) as c:
        assert c.info.dbname == "ventas_test", "nunca limpiar otra base"
        c.execute("TRUNCATE comprobantes, pagos, pedido_items, pedidos, productos, clientes RESTART IDENTITY CASCADE")
        c.execute("ALTER SEQUENCE comprobante_seq RESTART")
        c.execute("""INSERT INTO productos (sku, nombre, precio, stock, activo) VALUES
            ('TEC-001', 'Teclado mecánico', 1000.00, 5, true),
            ('MOU-001', 'Mouse óptico', 200.50, 10, true),
            ('OLD-001', 'Producto descontinuado', 50.00, 3, false),
            ('RAR-001', 'Edición limitada', 500.00, 1, true)""")
        c.execute("INSERT INTO clientes (nombre, email) VALUES ('Ana Pérez', 'ana@example.com')")


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
