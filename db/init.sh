#!/bin/sh
set -e
for db in ventas ventas_test; do
  psql -v ON_ERROR_STOP=1 -U postgres -c "CREATE DATABASE $db"
  psql -v ON_ERROR_STOP=1 -U postgres -d "$db" -f /sql/schema.sql
done
psql -v ON_ERROR_STOP=1 -U postgres -d ventas -f /sql/seed.sql
