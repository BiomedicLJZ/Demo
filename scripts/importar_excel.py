# /// script
# dependencies = ["openpyxl"]
# ///
"""Regenera db/seed.sql desde 'Data Final.xlsx' (hojas Articulos, Existencias, Clientes).
Uso: uv run scripts/importar_excel.py && docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d ventas -f /sql/seed.sql
Impuesto = Impuesto1/100 por producto (Impuesto2/3 se ignoran). Ignora ventas, sucursales, vendedores y CRM: el esquema no tiene dónde guardarlos."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import openpyxl

RAIZ = Path(__file__).resolve().parent.parent
q = lambda s: "'" + str(s).replace("'", "''") + "'"


def filas(wb, hoja):
    it = wb[hoja].iter_rows(values_only=True)
    cols = next(it)
    return [dict(zip(cols, r)) for r in it if any(c is not None for c in r)]


wb = openpyxl.load_workbook(RAIZ / "Data Final.xlsx", read_only=True, data_only=True)

stock = defaultdict(int)  # suma de todos los almacenes; una combinación ausente cuenta como 0
for e in filas(wb, "Existencias"):
    assert e["Disponible"] >= 0, e
    stock[e["Articulo"]] += int(e["Disponible"])

prods = []
for a in filas(wb, "Articulos"):
    assert a["PrecioLista"] > 0, a
    prods.append(f"  ({q(a['Articulo'])}, {q(a['Descripcion'])}, {round(a['PrecioLista'], 2)}, "
                 f"{stock[a['Articulo']]}, {'TRUE' if a['SeVende'] == 1 else 'FALSE'}, {Decimal(str(a['Impuesto1'])) / 100})")

# sin email en el origen: se sintetiza por ID (los nombres se repiten, p. ej. PÚBLICO EN GENERAL)
clis = [f"  ({q(c['Nombre'])}, {q('cliente-' + str(c['Cliente']) + '@demo.invalid')}, NULL)"
        for c in filas(wb, "Clientes")]

(RAIZ / "db" / "seed.sql").write_text(
    "TRUNCATE comprobantes, pagos, pedido_items, pedidos, productos, clientes RESTART IDENTITY CASCADE;\n"
    "ALTER SEQUENCE comprobante_seq RESTART;\n\n"
    "INSERT INTO productos (sku, nombre, precio, stock, activo, impuesto) VALUES\n" + ",\n".join(prods) + ";\n\n"
    "INSERT INTO clientes (nombre, email, telefono) VALUES\n" + ",\n".join(clis) + ";\n")
print(f"{len(prods)} productos, {len(clis)} clientes")
