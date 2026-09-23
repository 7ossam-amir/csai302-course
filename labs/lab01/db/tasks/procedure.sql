-- TODO: Update the requested order's status.
-- Consider how PostgreSQL constraints handle a status value outside the allowed set.
CREATE OR REPLACE PROCEDURE lab01.update_order_status(
    p_order_id bigint,
    p_new_status text
)
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE NOTICE 'Implement the status update for order %', p_order_id;
END;
$$;
