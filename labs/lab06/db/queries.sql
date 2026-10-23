-- This file is read-only. seed.sql has already run ANALYZE; if you change data,
-- run ANALYZE lab06.orders; in psql before comparing estimates again.

-- Check the loaded volumes and the deliberate skew.
SELECT 'customers' AS relation, count(*) AS rows FROM lab06.customers
UNION ALL
SELECT 'orders', count(*) FROM lab06.orders;

SELECT status, count(*) AS rows
FROM lab06.orders
GROUP BY status
ORDER BY status;

-- PostgreSQL's sampled statistics for only the Lab 6 columns.
SELECT schemaname, tablename, attname, null_frac, n_distinct,
       most_common_vals, most_common_freqs, histogram_bounds
FROM pg_stats
WHERE schemaname = 'lab06'
ORDER BY tablename, attname;

-- Run these before and after indexes.sql. EXPLAIN ANALYZE executes each SELECT.
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id FROM lab06.orders WHERE status = 'cancelled';

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id FROM lab06.orders WHERE status = 'paid';

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, status FROM lab06.orders WHERE customer_id = 1;

-- Repeat these result checks after indexes.sql. Counts and id bounds should agree.
SELECT count(*) AS matching_rows,
       md5(string_agg(id::text, ',' ORDER BY id)) AS ordered_id_digest
FROM lab06.orders WHERE status = 'cancelled';

SELECT count(*) AS matching_rows,
       md5(string_agg(id::text, ',' ORDER BY id)) AS ordered_id_digest
FROM lab06.orders WHERE status = 'paid';

SELECT count(*) AS matching_rows,
       md5(string_agg(id::text, ',' ORDER BY id)) AS ordered_id_digest
FROM lab06.orders WHERE customer_id = 1;
