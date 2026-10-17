"""Conexiones: `rw` para las herramientas de venta, `ro` para lecturas libres.

PostgreSQL por defecto (pools de psycopg). Con `sqlite:///ruta.db` usa un archivo SQLite: para demos
en máquinas sin Docker ni Postgres. Ambos exponen `with db.rw.connection() as c: c.execute(sql, params)`.
"""
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ventas.config import ConfigError

CENT = Decimal("0.01")


def _decimal(b: bytes) -> Decimal:
    # SQLite guarda 200.50 como REAL y lo devuelve como "200.5": mínimo 2 decimales, como NUMERIC(12,2) de Postgres
    d = Decimal(b.decode())
    return d.quantize(CENT) if d.as_tuple().exponent > -2 else d


sqlite3.register_adapter(Decimal, str)
sqlite3.register_converter("NUMERIC", _decimal)


def _sin_acentos(s: str | None) -> str | None:
    return s and "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _fila_dict(cur, fila):
    return {d[0]: v for d, v in zip(cur.description, fila)}


def _traducir(sql: str) -> str:
    """Dialecto de Postgres/psycopg -> SQLite, solo para el SQL propio de `servicio`."""
    sql = sql.replace("%s", "?")
    sql = re.sub(r"::\w+", "", sql)  # casts: SQLite no los necesita
    sql = re.sub(r"\bILIKE\b", "LIKE", sql)  # LIKE de SQLite ya ignora mayúsculas (ASCII; unaccent normaliza el resto)
    return re.sub(r"\s+FOR UPDATE\b", "", sql)  # el bloqueo lo da BEGIN IMMEDIATE


class _Conn(sqlite3.Connection):
    def execute(self, sql, params=None):
        # como psycopg: sin parámetros el SQL va tal cual (consulta_sql puede traer '%' en un LIKE)
        return super().execute(sql if params is None else _traducir(sql), params or ())


class _SqlitePool:
    def __init__(self, ruta: Path, rw: bool):
        self.ruta, self.rw = ruta, rw

    @contextmanager
    def connection(self):
        # isolation_level=None: las transacciones las abrimos nosotros
        c = sqlite3.connect(self.ruta, factory=_Conn, isolation_level=None, timeout=5,
                            detect_types=sqlite3.PARSE_DECLTYPES)
        try:
            c.row_factory = _fila_dict
            c.create_function("unaccent", 1, _sin_acentos, deterministic=True)
            c.execute("PRAGMA foreign_keys = ON")
            if self.rw:
                # un solo escritor a la vez desde el inicio: hace el papel de SELECT ... FOR UPDATE
                c.execute("BEGIN IMMEDIATE")
            else:
                c.execute("PRAGMA query_only = ON")  # el equivalente al rol ventas_ro
            yield c
            if self.rw:
                c.execute("COMMIT")
        finally:
            c.close()  # si hubo excepción la transacción abierta se descarta (rollback)

    def close(self) -> None:
        pass


class Db:
    def __init__(self, url_rw: str, url_ro: str):
        self.sqlite = url_rw.startswith("sqlite:")
        if self.sqlite:  # un solo archivo: url_ro se ignora y el solo-lectura de `ro` lo da query_only
            ruta = Path(url_rw.removeprefix("sqlite:///"))
            if not ruta.exists():
                raise ConfigError(f"No existe la base SQLite {ruta}. Créala con: uv run scripts/init_sqlite.py {ruta}")
            self.rw, self.ro = _SqlitePool(ruta, True), _SqlitePool(ruta, False)
            return
        kw = {"row_factory": dict_row}
        self.rw = ConnectionPool(url_rw, min_size=1, max_size=8, kwargs=kw, open=True)
        # read_only=True abre cada transacción como READ ONLY: set_config(..., false) no puede volver a read-write
        self.ro = ConnectionPool(url_ro, min_size=1, max_size=2, kwargs=kw, open=True,
                                 configure=lambda conn: setattr(conn, "read_only", True))
        self.rw.wait(timeout=5)  # PoolTimeout si Postgres no responde
        self.ro.wait(timeout=5)

    def close(self) -> None:
        self.rw.close()
        self.ro.close()
