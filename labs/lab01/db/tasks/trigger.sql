CREATE OR REPLACE FUNCTION lab01.reserve_product_stock()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE lab01.products
    SET stock = stock - NEW.quantity 
    WHERE id = NEW.product_id
      AND stock >= NEW.quantity;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Insufficient stock (or unknown product) for product %: requested %',
            NEW.product_id, NEW.quantity;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reserve_product_stock ON lab01.order_items;

CREATE TRIGGER trg_reserve_product_stock
BEFORE INSERT ON lab01.order_items
FOR EACH ROW
EXECUTE FUNCTION lab01.reserve_product_stock();