-- TODO: Reserve product stock when a new order item is inserted.
-- Test both an available quantity and a quantity greater than available stock.
CREATE OR REPLACE FUNCTION lab01.reserve_product_stock()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- NEW contains the row being inserted into order_items.
    -- Add the stock behavior, then decide what should happen when it cannot be reserved.
    RETURN NEW;
END;
$$;

-- TODO: Create a trigger that calls lab01.reserve_product_stock().
