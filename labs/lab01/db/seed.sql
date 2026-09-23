INSERT INTO lab01.customers (full_name, email)
VALUES
    ('Amina Hassan', 'amina@example.edu'),
    ('Omar Nabil', 'omar@example.edu'),
    ('Mariam Adel', 'mariam@example.edu')
ON CONFLICT (email) DO NOTHING;

INSERT INTO lab01.products (sku, product_name, unit_price, stock)
VALUES
    ('KB-001', 'Mechanical keyboard', 74.50, 12),
    ('MS-002', 'Wireless mouse', 29.99, 20),
    ('HD-003', 'USB-C hub', 44.00, 5),
    ('ST-004', 'Laptop stand', 38.75, 8)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO lab01.orders (order_ref, customer_id, status, created_at)
SELECT v.order_ref, c.id, v.status, v.created_at::timestamptz
FROM (
    VALUES
        ('ORD-1001', 'amina@example.edu', 'pending', '2026-02-10 09:15:00+00'),
        ('ORD-1002', 'omar@example.edu', 'paid', '2026-02-10 10:30:00+00'),
        ('ORD-1003', 'amina@example.edu', 'shipped', '2026-02-11 08:00:00+00'),
        ('ORD-1004', 'mariam@example.edu', 'pending', '2026-02-12 13:45:00+00')
) AS v(order_ref, email, status, created_at)
JOIN lab01.customers AS c ON c.email = v.email
ON CONFLICT (order_ref) DO NOTHING;

INSERT INTO lab01.order_items (order_id, product_id, quantity, unit_price)
SELECT o.id, p.id, v.quantity, p.unit_price
FROM (
    VALUES
        ('ORD-1001', 'KB-001', 1),
        ('ORD-1001', 'MS-002', 2),
        ('ORD-1002', 'HD-003', 1),
        ('ORD-1003', 'ST-004', 1),
        ('ORD-1004', 'MS-002', 1)
) AS v(order_ref, sku, quantity)
JOIN lab01.orders AS o ON o.order_ref = v.order_ref
JOIN lab01.products AS p ON p.sku = v.sku
ON CONFLICT (order_id, product_id) DO NOTHING;
