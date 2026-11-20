-- Optional and destructive: drops only the Lab 9 schema and its objects.
-- If a two-phase commit demo was interrupted, first run:
--   python labs/lab09/postgres_distributed_demo.py --mode cleanup
-- (a leftover prepared transaction keeps its locks and would block the DROP).
DROP SCHEMA IF EXISTS lab09 CASCADE;
