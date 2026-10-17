"""Crea la BD SQLite de demo (esquema + catálogo de db/seed.sql): sin Docker ni PostgreSQL.

Uso: uv run scripts/init_sqlite.py [demo.db]    y en .env: DATABASE_URL=sqlite:///demo.db
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "db"
ruta = Path(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
if ruta.exists():
    sys.exit(f"{ruta} ya existe; bórrala si quieres recrearla.")

# seed.sql abre con TRUNCATE/ALTER SEQUENCE (solo Postgres); el resto son INSERT estándar
seed = "\n".join(l for l in (DB / "seed.sql").read_text().splitlines() if not l.startswith(("TRUNCATE", "ALTER SEQUENCE")))
con = sqlite3.connect(ruta)
con.executescript((DB / "schema_sqlite.sql").read_text() + seed)
n = con.execute("SELECT count(*) FROM productos").fetchone()[0]
con.close()
print(f"{ruta} creada con {n} productos. En .env: DATABASE_URL=sqlite:///{ruta}")
