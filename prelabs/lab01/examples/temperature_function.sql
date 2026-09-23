-- A small example of reusable database-side computation.
CREATE SCHEMA IF NOT EXISTS lab01;

CREATE OR REPLACE FUNCTION lab01.celsius_to_fahrenheit(p_celsius numeric)
RETURNS numeric
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT p_celsius * 9 / 5 + 32;
$$;

SELECT lab01.celsius_to_fahrenheit(20);
