"""Pools de conexión: `rw` para las herramientas de venta, `ro` para lecturas libres."""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Db:
    def __init__(self, url_rw: str, url_ro: str):
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
