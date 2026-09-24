-- 1) Simple: no parameters, only reads and prints a message
CREATE OR REPLACE PROCEDURE lab01.count_pending_orders()
LANGUAGE plpgsql
AS $$
DECLARE
    v_count integer;
BEGIN
    SELECT count(*) INTO v_count
    FROM lab01.orders
    WHERE status = 'pending';

    RAISE NOTICE 'Pending orders: %', v_count;
END;
$$;

-- 2) Input parameters: the lab's required procedure
CREATE OR REPLACE PROCEDURE lab01.update_order_status(
    p_order_id bigint,
    p_new_status text
)
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE lab01.orders
    SET status = p_new_status
    WHERE id = p_order_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Order % does not exist', p_order_id;
    END IF;
END;
$$;

-- 3) Output parameters: returns values to the caller
CREATE OR REPLACE PROCEDURE lab01.get_order_summary(
    p_order_id       bigint,
    OUT p_total      numeric,
    OUT p_item_count integer
)
LANGUAGE plpgsql
AS $$
BEGIN
    SELECT COALESCE(SUM(quantity * unit_price), 0), COUNT(*)
    INTO p_total, p_item_count
    FROM lab01.order_items
    WHERE order_id = p_order_id;
END;
$$;