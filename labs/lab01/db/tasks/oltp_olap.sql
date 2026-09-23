-- Small transactional lookup: an order identified by its unique reference.
SELECT order_ref, status, created_at
FROM lab01.orders
WHERE order_ref = 'ORD-1001';

-- Introductory analytical query: aggregate order value by customer.
SELECT
    c.full_name,
    count(DISTINCT o.id) AS order_count,
    coalesce(sum(oi.quantity * oi.unit_price), 0)::numeric(12, 2) AS total_value
FROM lab01.customers AS c
LEFT JOIN lab01.orders AS o ON o.customer_id = c.id
LEFT JOIN lab01.order_items AS oi ON oi.order_id = o.id
GROUP BY c.id, c.full_name
ORDER BY total_value DESC;

-- EXPLAIN ANALYZE executes the query. Use it only with these read-only SELECTs.
EXPLAIN ANALYZE
SELECT order_ref, status
FROM lab01.orders
WHERE order_ref = 'ORD-1001';
