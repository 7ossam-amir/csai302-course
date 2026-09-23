# Pre-lab 1 — Database programming and secure access

## Before the live lab

Watch the Lab 1 recording on the course platform. The TA should add the recording link here before publishing the lab.

The recording prepares you to use Python, Psycopg, and PostgreSQL; it explains functions, procedures, triggers, OLTP and OLAP query patterns, and parameterized queries. It uses short examples rather than the live lab's order-system exercises.

## Prepare your environment

Follow the one-time setup in ../../docs/environment-setup.md. Confirm that:

- the course .venv is active and the requirements are installed;
- PostgreSQL reports healthy in Docker Compose;
- you can connect to csai302 with DBeaver or psql;
- the Python connectivity check succeeds.

If a check fails, bring the error and the step where it occurred to the live lab.

## Small examples

- examples/temperature_function.sql introduces a simple reusable SQL function.
- examples/parameter_binding.py shows Psycopg keeping a supplied string as data.

Neither example implements the order-total function, order-status procedure, inventory trigger, or order search used in the live lab.
