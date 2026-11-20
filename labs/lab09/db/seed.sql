-- Repeatable fixture for the partitioning and two-phase commit demos.
-- doc_chunks is filled by postgres_distributed_demo.py --mode vectors.
TRUNCATE lab09.orders, lab09.customers, lab09.stores, lab09.shard1_accounts, lab09.shard2_accounts;

INSERT INTO lab09.customers (id, name, region)
SELECT g, 'customer ' || g, (ARRAY['Cairo', 'Giza', 'Alexandria', 'Aswan'])[1 + g % 4]
FROM generate_series(1, 20000) AS g;

INSERT INTO lab09.orders (id, customer_id, order_date, amount)
SELECT g, 1 + (g * 7919) % 20000, DATE '2026-01-01' + (g % 365), round((g % 997)::numeric / 3, 2)
FROM generate_series(1, 100000) AS g;

INSERT INTO lab09.stores (id, region, city)
VALUES (1, 'Cairo', 'Nasr City'), (2, 'Giza', 'Dokki'), (3, 'Alexandria', 'Smouha'),
       (4, 'Alexandria', 'Miami'), (5, 'Aswan', 'Aswan'), (6, 'Luxor', 'Luxor');

INSERT INTO lab09.shard1_accounts VALUES ('alice', 100), ('bob', 40);
INSERT INTO lab09.shard2_accounts VALUES ('carol', 50), ('dave', 10);

ANALYZE lab09.orders, lab09.customers, lab09.stores;
