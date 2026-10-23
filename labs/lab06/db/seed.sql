INSERT INTO lab06.customers (id, full_name, segment, created_at)
SELECT g,
       'Customer ' || lpad(g::text, 4, '0'),
       CASE WHEN g % 20 = 0 THEN 'business'
            WHEN g % 5 = 0 THEN 'plus'
            ELSE 'standard' END,
       timestamptz '2025-01-01 00:00:00+00' + g * interval '1 day'
FROM generate_series(1, 1000) AS series(g)
ON CONFLICT (id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('lab06.customers', 'id'),
              (SELECT max(id) FROM lab06.customers), true);

INSERT INTO lab06.orders (id, customer_id, status, total_amount, placed_at)
SELECT g,
       CASE WHEN g % 10 = 0 THEN 1 ELSE ((g * 37) % 999) + 2 END,
       CASE WHEN g <= 96000 THEN 'paid'
            WHEN g <= 117600 THEN 'shipped'
            WHEN g <= 118800 THEN 'pending'
            ELSE 'cancelled' END,
       round((10 + (g % 9900) / 100.0)::numeric, 2),
       timestamptz '2026-01-01 00:00:00+00' + (g % 365) * interval '1 day'
FROM generate_series(1, 120000) AS series(g)
ON CONFLICT (id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('lab06.orders', 'id'),
              (SELECT max(id) FROM lab06.orders), true);

ANALYZE lab06.customers;
ANALYZE lab06.orders;
