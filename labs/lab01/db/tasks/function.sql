-- TODO: Replace the placeholder query with the order total calculation.
-- The function should return zero when the order has no items.
CREATE OR REPLACE FUNCTION lab01.calculate_order_total(p_order_id bigint)
RETURNS numeric(12, 2)
LANGUAGE SQL
STABLE
AS $$
    SELECT 0::numeric(12, 2);
$$;
