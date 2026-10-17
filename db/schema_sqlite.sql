-- Mismo modelo que schema.sql, para demos sin Postgres (DATABASE_URL=sqlite:///demo.db).
-- Sin roles ni secuencias: el solo-lectura lo da PRAGMA query_only y el número de comprobante sale de MAX(id)+1.
-- NUMERIC se mantiene como tipo declarado: db.py lo convierte a Decimal al leer.
PRAGMA journal_mode = WAL;

CREATE TABLE clientes (
  id       INTEGER PRIMARY KEY,
  nombre   TEXT NOT NULL,
  email    TEXT NOT NULL UNIQUE,
  telefono TEXT
);

CREATE TABLE productos (
  id     INTEGER PRIMARY KEY,
  sku    TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  precio NUMERIC(12,2) NOT NULL CHECK (precio >= 0),
  stock  INTEGER NOT NULL CHECK (stock >= 0),
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  impuesto NUMERIC(5,4) CHECK (impuesto >= 0 AND impuesto < 1)  -- fracción (0.16); NULL = tasa global TASA_IMPUESTO
);

CREATE TABLE pedidos (
  id         INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  estado     TEXT NOT NULL DEFAULT 'pendiente_pago' CHECK (estado IN ('pendiente_pago', 'pagado')),
  subtotal   NUMERIC(12,2) NOT NULL,
  impuesto   NUMERIC(12,2) NOT NULL,
  total      NUMERIC(12,2) NOT NULL,
  creado_en  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP  -- UTC, 'YYYY-MM-DD HH:MM:SS'
);

CREATE TABLE pedido_items (
  pedido_id       INTEGER NOT NULL REFERENCES pedidos(id),
  producto_id     INTEGER NOT NULL REFERENCES productos(id),
  cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
  precio_unitario NUMERIC(12,2) NOT NULL,
  PRIMARY KEY (pedido_id, producto_id)
);

CREATE TABLE pagos (
  id         INTEGER PRIMARY KEY,
  pedido_id  INTEGER NOT NULL UNIQUE REFERENCES pedidos(id),
  monto      NUMERIC(12,2) NOT NULL,
  metodo     TEXT NOT NULL,
  referencia TEXT NOT NULL,
  pagado_en  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE comprobantes (
  id         INTEGER PRIMARY KEY,
  pedido_id  INTEGER NOT NULL UNIQUE REFERENCES pedidos(id),
  numero     TEXT NOT NULL UNIQUE,
  emitido_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
