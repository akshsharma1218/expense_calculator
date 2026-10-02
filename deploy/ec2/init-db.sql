CREATE SCHEMA IF NOT EXISTS expense AUTHORIZATION expense_calculator_user;
GRANT ALL PRIVILEGES ON SCHEMA expense TO expense_calculator_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA expense GRANT ALL ON TABLES TO expense_calculator_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA expense GRANT ALL ON SEQUENCES TO expense_calculator_user;
ALTER ROLE expense_calculator_user SET search_path TO expense;
