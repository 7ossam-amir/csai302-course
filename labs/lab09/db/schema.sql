CREATE SCHEMA IF NOT EXISTS lab09;

-- Range partitioning: one partition per quarter of 2026.
CREATE TABLE IF NOT EXISTS lab09.orders (
    id bigint NOT NULL,
    customer_id integer NOT NULL,
    order_date date NOT NULL,
    amount numeric(10, 2) NOT NULL CHECK (amount >= 0),
    PRIMARY KEY (id, order_date)          -- the partition key must be part of the primary key
) PARTITION BY RANGE (order_date);
CREATE TABLE IF NOT EXISTS lab09.orders_2026q1 PARTITION OF lab09.orders FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS lab09.orders_2026q2 PARTITION OF lab09.orders FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS lab09.orders_2026q3 PARTITION OF lab09.orders FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS lab09.orders_2026q4 PARTITION OF lab09.orders FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');

-- Hash partitioning: four partitions by customer id.
CREATE TABLE IF NOT EXISTS lab09.customers (
    id integer PRIMARY KEY,
    name text NOT NULL,
    region text NOT NULL
) PARTITION BY HASH (id);
CREATE TABLE IF NOT EXISTS lab09.customers_h0 PARTITION OF lab09.customers FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE IF NOT EXISTS lab09.customers_h1 PARTITION OF lab09.customers FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE IF NOT EXISTS lab09.customers_h2 PARTITION OF lab09.customers FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE IF NOT EXISTS lab09.customers_h3 PARTITION OF lab09.customers FOR VALUES WITH (MODULUS 4, REMAINDER 3);

-- List partitioning: one partition per region, plus a default.
CREATE TABLE IF NOT EXISTS lab09.stores (
    id integer NOT NULL,
    region text NOT NULL,
    city text NOT NULL,
    PRIMARY KEY (id, region)
) PARTITION BY LIST (region);
CREATE TABLE IF NOT EXISTS lab09.stores_cairo PARTITION OF lab09.stores FOR VALUES IN ('Cairo', 'Giza');
CREATE TABLE IF NOT EXISTS lab09.stores_alex PARTITION OF lab09.stores FOR VALUES IN ('Alexandria');
CREATE TABLE IF NOT EXISTS lab09.stores_other PARTITION OF lab09.stores DEFAULT;

-- Two "shards" for the two-phase commit demo (separate tables in one database).
CREATE TABLE IF NOT EXISTS lab09.shard1_accounts (owner text PRIMARY KEY, balance integer NOT NULL CHECK (balance >= 0));
CREATE TABLE IF NOT EXISTS lab09.shard2_accounts (owner text PRIMARY KEY, balance integer NOT NULL CHECK (balance >= 0));

-- Vectors without an extension: a float8[] column and an exact cosine function.
CREATE TABLE IF NOT EXISTS lab09.doc_chunks (
    id integer PRIMARY KEY,
    source text NOT NULL,
    heading text NOT NULL,
    body text NOT NULL,
    embedding float8[] NOT NULL
);

CREATE OR REPLACE FUNCTION lab09.cosine(a float8[], b float8[]) RETURNS float8
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT sum(x * y) / NULLIF(sqrt(sum(x * x)) * sqrt(sum(y * y)), 0)
    FROM unnest(a, b) AS t(x, y)
$$;
