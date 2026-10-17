CREATE EXTENSION IF NOT EXISTS unaccent;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ventas_rw') THEN
    CREATE ROLE ventas_rw LOGIN PASSWORD 'ventas_rw';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ventas_ro') THEN
    CREATE ROLE ventas_ro LOGIN PASSWORD 'ventas_ro';
  END IF;
END $$;
ALTER ROLE ventas_ro SET default_transaction_read_only = on;
ALTER ROLE ventas_ro SET statement_timeout = '5s';

CREATE TABLE clientes (
  id       BIGSERIAL PRIMARY KEY,
  nombre   TEXT NOT NULL,
  email    TEXT NOT NULL UNIQUE,
  telefono TEXT
);

CREATE TABLE productos (
  id     BIGSERIAL PRIMARY KEY,
  sku    TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  precio NUMERIC(12,2) NOT NULL CHECK (precio >= 0),
  stock  INTEGER NOT NULL CHECK (stock >= 0),
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  impuesto NUMERIC(5,4) CHECK (impuesto >= 0 AND impuesto < 1)  -- fracción (0.16); NULL = tasa global TASA_IMPUESTO
);

CREATE TABLE pedidos (
  id         BIGSERIAL PRIMARY KEY,
  cliente_id BIGINT NOT NULL REFERENCES clientes(id),
  estado     TEXT NOT NULL DEFAULT 'pendiente_pago' CHECK (estado IN ('pendiente_pago', 'pagado')),
  subtotal   NUMERIC(12,2) NOT NULL,
  impuesto   NUMERIC(12,2) NOT NULL,
  total      NUMERIC(12,2) NOT NULL,
  creado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pedido_items (
  pedido_id       BIGINT NOT NULL REFERENCES pedidos(id),
  producto_id     BIGINT NOT NULL REFERENCES productos(id),
  cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
  precio_unitario NUMERIC(12,2) NOT NULL,
  PRIMARY KEY (pedido_id, producto_id)
);

CREATE TABLE pagos (
  id         BIGSERIAL PRIMARY KEY,
  pedido_id  BIGINT NOT NULL UNIQUE REFERENCES pedidos(id),
  monto      NUMERIC(12,2) NOT NULL,
  metodo     TEXT NOT NULL,
  referencia TEXT NOT NULL,
  pagado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE comprobante_seq;
CREATE TABLE comprobantes (
  id         BIGSERIAL PRIMARY KEY,
  pedido_id  BIGINT NOT NULL UNIQUE REFERENCES pedidos(id),
  numero     TEXT NOT NULL UNIQUE,
  emitido_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT USAGE ON SCHEMA public TO ventas_rw, ventas_ro;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO ventas_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ventas_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ventas_ro;
