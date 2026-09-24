-- TODO: Replace the placeholder query with the order total calculation.
-- The function should return zero when the order has no items.
CREATE OR REPLACE FUNCTION lab01.calculate_order_total(p_order_id bigint)
RETURNS numeric(12, 2)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN (
        SELECT COALESCE(SUM(quantity * unit_price), 0)::numeric(12, 2)
        FROM lab01.order_items
        WHERE order_id = p_order_id
    );
END;
$$;

