"""Reglas de negocio de ventas. Única capa que escribe en la BD; la comparten las herramientas y el CLI."""
import re
import sqlite3
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal

import psycopg

from ventas.db import Db

CENT = Decimal("0.01")
MAX_FILAS = 200
METODOS_PAGO = ("tarjeta", "transferencia", "efectivo")


class ErrorDeNegocio(Exception):
    """Error esperado cuyo mensaje se le puede explicar al cliente."""


def _dinero(valor) -> Decimal:
    return Decimal(str(valor)).quantize(CENT, ROUND_HALF_UP)


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


PALABRAS_VACIAS = {"de", "del", "la", "el", "los", "las", "un", "una", "y", "para", "con", "en"}


def _raiz(palabra: str) -> str:
    """Singular aproximado (agujas -> aguja, collares -> collar): la raíz es subcadena del nombre en singular."""
    if palabra.endswith("es") and len(palabra) > 4:
        return palabra[:-2]
    if palabra.endswith("s") and len(palabra) > 3:
        return palabra[:-1]
    return palabra


def buscar_productos(db: Db, texto: str, limite: int = 10) -> list[dict]:
    texto = (texto or "").strip()
    if not texto:
        raise ErrorDeNegocio("Indica qué producto quieres buscar.")
    # cada palabra debe aparecer en el nombre, en cualquier orden; si todas son vacías se busca el texto tal cual
    palabras = [_raiz(w) for w in texto.lower().split() if w not in PALABRAS_VACIAS] or [texto.lower()]
    cond = " AND ".join(["unaccent(nombre) ILIKE unaccent(%s::text) ESCAPE '\\'"] * len(palabras))  # SQLite no tiene escape por defecto
    with db.ro.connection() as c:
        return c.execute(
            f"""SELECT sku, nombre, precio, stock FROM productos
               WHERE activo AND (({cond}) OR sku ILIKE %s ESCAPE '\\')
               ORDER BY nombre LIMIT %s""",
            [f"%{_escapar_like(w)}%" for w in palabras] + [f"%{_escapar_like(texto)}%", limite],
        ).fetchall()


def listar_catalogo(db: Db) -> list[dict]:
    with db.ro.connection() as c:
        return c.execute(
            "SELECT sku, nombre, precio, stock FROM productos WHERE activo ORDER BY nombre"
        ).fetchall()


def registrar_cliente(db: Db, nombre: str, email: str, telefono: str | None = None) -> dict:
    nombre = (nombre or "").strip()
    email = (email or "").strip().lower()
    if not nombre:
        raise ErrorDeNegocio("Falta el nombre del cliente.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ErrorDeNegocio("El email no es válido.")
    with db.rw.connection() as c:
        # DO NOTHING no devuelve fila si el email ya existía: entonces se lee la existente
        fila = c.execute(
            """INSERT INTO clientes (nombre, email, telefono) VALUES (%s, %s, %s)
               ON CONFLICT (email) DO NOTHING
               RETURNING id, nombre, email, telefono""",
            (nombre, email, (telefono or "").strip() or None),
        ).fetchone()
        nuevo = fila is not None
        if not nuevo:
            fila = c.execute("SELECT id, nombre, email, telefono FROM clientes WHERE email = %s", (email,)).fetchone()
        return {**fila, "nuevo": nuevo}


def _cantidad(sku: str, valor) -> int | Decimal:
    """Número > 0 con hasta 3 decimales (productos por kg); entero si lo es, para no mostrar «2.0»."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        raise ErrorDeNegocio(f"Cantidad inválida para {sku}: debe ser un número mayor a 0.")
    d = Decimal(str(valor))
    if not d.is_finite() or d <= 0 or d * 1000 != (d * 1000).to_integral_value():
        raise ErrorDeNegocio(f"Cantidad inválida para {sku}: debe ser mayor a 0 y tener hasta 3 decimales.")
    return int(d) if d == d.to_integral_value() else d


def _normalizar_items(items: list[dict]) -> dict[str, int | Decimal]:
    """[{'sku','cantidad'}] -> {SKU: cantidad}: sku en mayúsculas, duplicados sumados, cantidades validadas."""
    if not items:
        raise ErrorDeNegocio("El pedido no tiene productos.")
    resultado: dict[str, int | Decimal] = {}
    for it in items:
        sku = str(it.get("sku") or "").strip().upper()
        if not sku:
            raise ErrorDeNegocio("Falta el SKU de un producto.")
        suma = resultado.get(sku, 0) + _cantidad(sku, it.get("cantidad"))
        resultado[sku] = int(suma) if suma == int(suma) else suma
    return resultado


def _marcas(pedido: dict) -> str:
    """'%s, %s, ...' para `sku IN (...)`: portable, a diferencia de `= ANY(%s)` que es solo de Postgres."""
    return ", ".join(["%s"] * len(pedido))


def _armar_cotizacion(pedido: dict[str, int | Decimal], filas: list[dict], tasa: Decimal) -> dict:
    por_sku = {f["sku"]: f for f in filas}
    faltan = [s for s in pedido if s not in por_sku]
    if faltan:
        raise ErrorDeNegocio("Productos no encontrados o no disponibles: " + ", ".join(faltan))
    lineas, subtotal, impuesto = [], Decimal("0.00"), Decimal(0)
    for sku, cantidad in pedido.items():
        f = por_sku[sku]
        if f["stock"] < cantidad:
            raise ErrorDeNegocio(
                f"Stock insuficiente de {sku} ({f['nombre']}): pediste {cantidad}, hay {f['stock']}."
            )
        importe = _dinero(f["precio"] * cantidad)
        lineas.append({"sku": sku, "nombre": f["nombre"], "cantidad": cantidad,
                       "precio_unitario": f["precio"], "importe": importe})
        subtotal += importe
        impuesto += importe * (tasa if f["impuesto"] is None else f["impuesto"])  # tasa propia del producto, o la global
    impuesto = _dinero(impuesto)
    return {"lineas": lineas, "subtotal": subtotal, "impuesto": impuesto, "total": subtotal + impuesto}


def cotizar(db: Db, items: list[dict], tasa: Decimal) -> dict:
    pedido = _normalizar_items(items)
    with db.ro.connection() as c:
        filas = c.execute(
            f"SELECT sku, nombre, precio, stock, impuesto FROM productos WHERE activo AND sku IN ({_marcas(pedido)})",
            list(pedido),
        ).fetchall()
    return _armar_cotizacion(pedido, filas, tasa)


def crear_pedido(db: Db, cliente_id: int, items: list[dict], tasa: Decimal) -> dict:
    pedido = _normalizar_items(items)
    with db.rw.connection() as c:  # una transacción: commit al salir, rollback si hay excepción
        if not c.execute("SELECT 1 FROM clientes WHERE id = %s", (cliente_id,)).fetchone():
            raise ErrorDeNegocio(f"No existe el cliente {cliente_id}.")
        # ORDER BY id + FOR UPDATE: bloqueo en orden estable (sin deadlocks) y stock releído tras esperar
        filas = c.execute(
            f"""SELECT id, sku, nombre, precio, stock, impuesto FROM productos
               WHERE activo AND sku IN ({_marcas(pedido)}) ORDER BY id FOR UPDATE""",
            list(pedido),
        ).fetchall()
        cot = _armar_cotizacion(pedido, filas, tasa)
        ped = c.execute(
            """INSERT INTO pedidos (cliente_id, subtotal, impuesto, total) VALUES (%s, %s, %s, %s)
               RETURNING id, estado""",
            (cliente_id, cot["subtotal"], cot["impuesto"], cot["total"]),
        ).fetchone()
        ids = {f["sku"]: f["id"] for f in filas}
        for l in cot["lineas"]:
            c.execute(
                "INSERT INTO pedido_items (pedido_id, producto_id, cantidad, precio_unitario) VALUES (%s, %s, %s, %s)",
                (ped["id"], ids[l["sku"]], l["cantidad"], l["precio_unitario"]),
            )
            c.execute("UPDATE productos SET stock = ROUND(stock - %s, 3) WHERE id = %s", (l["cantidad"], ids[l["sku"]]))
    return {"pedido_id": ped["id"], "estado": ped["estado"], **cot}


def registrar_pago(db: Db, pedido_id: int, monto, metodo: str) -> dict:
    metodo = (metodo or "").strip().lower()
    if metodo not in METODOS_PAGO:
        raise ErrorDeNegocio("Método de pago inválido. Usa: " + ", ".join(METODOS_PAGO) + ".")
    try:
        monto = _dinero(monto)
    except ArithmeticError:
        raise ErrorDeNegocio("El monto no es un número válido.") from None
    with db.rw.connection() as c:
        p = c.execute("SELECT estado, total FROM pedidos WHERE id = %s FOR UPDATE", (pedido_id,)).fetchone()
        if not p:
            raise ErrorDeNegocio(f"No existe el pedido {pedido_id}.")
        if p["estado"] == "pagado":
            raise ErrorDeNegocio(f"El pedido {pedido_id} ya está pagado.")
        if monto != p["total"]:
            raise ErrorDeNegocio(f"El monto {monto} no coincide con el total del pedido ({p['total']}).")
        referencia = "SIM-" + uuid.uuid4().hex[:8].upper()  # pago simulado: sin pasarela
        c.execute(
            "INSERT INTO pagos (pedido_id, monto, metodo, referencia) VALUES (%s, %s, %s, %s)",
            (pedido_id, monto, metodo, referencia),
        )
        c.execute("UPDATE pedidos SET estado = 'pagado' WHERE id = %s", (pedido_id,))
    return {"pedido_id": pedido_id, "monto": monto, "metodo": metodo, "referencia": referencia, "estado": "pagado"}


def emitir_comprobante(db: Db, pedido_id: int) -> dict:
    with db.rw.connection() as c:
        p = c.execute("SELECT estado FROM pedidos WHERE id = %s FOR UPDATE", (pedido_id,)).fetchone()
        if not p:
            raise ErrorDeNegocio(f"No existe el pedido {pedido_id}.")
        if p["estado"] != "pagado":
            raise ErrorDeNegocio(f"El pedido {pedido_id} aún no está pagado; no se puede emitir comprobante.")
        # SELECT antes de INSERT (no ON CONFLICT) para no consumir números de la secuencia al repetir
        fila = c.execute(
            "SELECT numero, emitido_en FROM comprobantes WHERE pedido_id = %s", (pedido_id,)
        ).fetchone()
        if fila is None:
            # SQLite no tiene secuencias; el MAX+1 es seguro porque BEGIN IMMEDIATE serializa a los escritores
            numero = ("'COMP-' || printf('%06d', (SELECT COALESCE(MAX(id), 0) + 1 FROM comprobantes))" if db.sqlite
                      else "'COMP-' || lpad(nextval('comprobante_seq')::text, 6, '0')")
            fila = c.execute(
                f"""INSERT INTO comprobantes (pedido_id, numero) VALUES (%s, {numero})
                    RETURNING numero, emitido_en""",
                (pedido_id,),
            ).fetchone()
    return {"pedido_id": pedido_id, **fila}


def obtener_pedido(db: Db, pedido_id: int) -> dict:
    with db.ro.connection() as c:
        p = c.execute(
            """SELECT p.id, p.estado, p.subtotal, p.impuesto, p.total, p.creado_en,
                      cl.nombre AS cliente, cl.email
               FROM pedidos p JOIN clientes cl ON cl.id = p.cliente_id WHERE p.id = %s""",
            (pedido_id,),
        ).fetchone()
        if not p:
            raise ErrorDeNegocio(f"No existe el pedido {pedido_id}.")
        items = c.execute(
            """SELECT pr.sku, pr.nombre, i.cantidad, i.precio_unitario
               FROM pedido_items i JOIN productos pr ON pr.id = i.producto_id
               WHERE i.pedido_id = %s ORDER BY pr.sku""",
            (pedido_id,),
        ).fetchall()
        pago = c.execute(
            "SELECT monto, metodo, referencia, pagado_en FROM pagos WHERE pedido_id = %s", (pedido_id,)
        ).fetchone()
        comprobante = c.execute(
            "SELECT numero, emitido_en FROM comprobantes WHERE pedido_id = %s", (pedido_id,)
        ).fetchone()
    return {**p, "items": items, "pago": pago, "comprobante": comprobante}


def consultar_sql(db: Db, sql: str) -> dict:
    """SELECT libre. Defensa en capas: regex, subconsulta (rompe multi-sentencia y CTE que modifica datos),
    rol ventas_ro de solo lectura y statement_timeout de 5 s configurado en el rol (en SQLite: query_only y
    un progress handler que aborta a los 5 s)."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not re.match(r"(?is)(select|with)\b", sql):
        raise ErrorDeNegocio("Solo se permiten consultas SELECT.")
    try:
        with db.ro.connection() as c:
            # SET LOCAL en cada consulta: un set_config(..., false) previo persiste en la conexión del pool
            if db.sqlite:
                limite = time.monotonic() + 5
                c.set_progress_handler(lambda: time.monotonic() > limite, 10_000)  # True => aborta la consulta
            else:
                c.execute("SET LOCAL statement_timeout = '5s'")
            # saltos de línea alrededor de `sql` para que un comentario `--` final no se coma el paréntesis
            filas = c.execute(f"SELECT * FROM (\n{sql}\n) AS q LIMIT {MAX_FILAS + 1}").fetchall()
    except (psycopg.Error, sqlite3.Error) as e:
        detalle = e.diag.message_primary if isinstance(e, psycopg.Error) else None
        raise ErrorDeNegocio(f"La consulta falló: {detalle or e}") from e
    return {"filas": filas[:MAX_FILAS], "truncado": len(filas) > MAX_FILAS}
