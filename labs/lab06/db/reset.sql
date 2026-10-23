-- DESTRUCTIVE AND OPTIONAL: removes every object and row in the Lab 6 schema.
-- This does not drop the shared csai302 database or Docker volume.
DROP SCHEMA IF EXISTS lab06 CASCADE;
