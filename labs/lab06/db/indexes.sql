-- Apply only after the first EXPLAIN observations. These indexes belong only
-- to Lab 6 tables and are safe to run more than once.
CREATE INDEX IF NOT EXISTS orders_status_idx ON lab06.orders (status);
CREATE INDEX IF NOT EXISTS orders_customer_idx ON lab06.orders (customer_id);
