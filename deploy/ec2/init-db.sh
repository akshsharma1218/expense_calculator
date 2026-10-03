#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${POSTGRES_DB:-expense_calculator_db}"
DB_USER="${POSTGRES_USER:-expense_calculator_user}"

if ! psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
  createdb -U "$DB_USER" -O "$DB_USER" "$DB_NAME"
fi

psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" <<'SQL'
CREATE SCHEMA IF NOT EXISTS expense AUTHORIZATION expense_calculator_user;
GRANT ALL PRIVILEGES ON SCHEMA expense TO expense_calculator_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA expense GRANT ALL ON TABLES TO expense_calculator_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA expense GRANT ALL ON SEQUENCES TO expense_calculator_user;
ALTER ROLE expense_calculator_user SET search_path TO expense;
SQL
