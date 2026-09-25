# Lab 1 — Database programming and secure access

Duration: 2 hours. Discussion happens throughout the lab rather than as a separate session.

## Learning goals

- Use the course Python environment to connect to PostgreSQL through Psycopg.
- Implement and distinguish a reusable function and a command-style procedure.
- Implement a trigger and observe its behavior on valid and invalid stock requests.
- Compare a small transactional lookup with an analytical join and aggregation.
- Demonstrate SQL injection and repair the query with parameter binding.

## Provided

- PostgreSQL Compose service and persistent course database.
- Mini order-system schema and sample data in db/.
- Python connection helper and connectivity check.
- Vulnerable Python query and an unfinished parameterized-query starter.
- SQL task files for the function, procedure, trigger, and query comparison.

## Student work

- Implement lab01.calculate_order_total(order_id).
- Implement lab01.update_order_status(order_id, status).
- Implement a stock-reservation trigger for inserted order items.
- Try the insufficient-stock case and explain the outcome.
- Compare the OLTP and analytical queries using their results and, if useful, introductory EXPLAIN ANALYZE observations.
- Explain the vulnerability in the supplied Python example and complete the parameterized-query starter.

For this lab, the function is used to return a value that can be called from a query, while the procedure is invoked with CALL to update an order. Present this as the intended use in the exercise, not as a strict rule that PostgreSQL functions cannot modify data.

## Live sequence

| Time | Activity |
| --- | --- |
| 0–15 min | Environment verification and troubleshooting buffer |
| 15–25 min | Inspect the provided schema and sample data |
| 25–45 min | Implement and discuss the function |
| 45–60 min | Implement and discuss the procedure |
| 60–85 min | Implement the trigger, test insufficient stock, and discuss |
| 85–100 min | Compare OLTP and OLAP query patterns |
| 100–115 min | Python access, injection demonstration, and parameterized fix |
| 115–120 min | Recap, commit, and final questions |

## Discussion prompts

- What is the difference between calling a function in a query and invoking a procedure with CALL?
- Could a constraint express the stock rule? What does the trigger add?
- What do NEW and OLD represent? When is each available?
- What happens to the insert if the trigger raises an error?
- Why should SQL instructions and user-supplied values remain separate?
- What could go wrong if two customers request the final item concurrently?

The concurrency question previews transaction behavior. The starter trigger is not presented as a complete concurrency-control solution.

## Database preparation

From the course repository root, run db/schema.sql and then db/seed.sql against the csai302 database. DBeaver users can open and execute each file. For a terminal workflow, pipe each file to psql inside the PostgreSQL container:

PowerShell:

    Get-Content labs/lab01/db/schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    Get-Content labs/lab01/db/seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

macOS or Linux:

    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/schema.sql
    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/seed.sql

Inspect the loaded objects and sample rows:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "\dt lab01.*"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT * FROM lab01.customers;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT * FROM lab01.orders;"

Substitute values from .env if you changed the local username or database name.

## Reset Lab 1 data

Only run this when you intend to discard Lab 1 objects. Execute db/reset.sql, then db/schema.sql, then db/seed.sql. This drops only schema lab01; it does not recreate the course database or remove the Docker volume.

## Run and test commands (Windows Command Prompt)

Run every command from the repository root.

Start PostgreSQL and check that it is healthy:

    docker compose --env-file .env -f infra/compose.yaml up -d postgres
    docker compose --env-file .env -f infra/compose.yaml ps

Load the schema, the sample data, and the task files:

    type labs\lab01\db\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\tasks\function.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\tasks\procedure.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\tasks\trigger.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

Function:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT o.order_ref, lab01.calculate_order_total(o.id) AS total FROM lab01.orders o ORDER BY o.id;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT lab01.calculate_order_total(id) FROM lab01.orders WHERE order_ref = 'ORD-1001';"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT lab01.calculate_order_total(999999);"

Procedures (look up the order id first; ids depend on how the seed inserted the rows):

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.count_pending_orders();"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT id, order_ref, status FROM lab01.orders ORDER BY order_ref;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.update_order_status(2, 'paid');"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.update_order_status(2, 'refunded');"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.update_order_status(999999, 'paid');"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.get_order_summary(2, NULL, NULL);"

The `refunded` status and order 999999 are expected to fail.

Trigger:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT sku, stock FROM lab01.products ORDER BY sku;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "INSERT INTO lab01.order_items (order_id, product_id, quantity, unit_price) SELECT o.id, p.id, 2, p.unit_price FROM lab01.orders o, lab01.products p WHERE o.order_ref = 'ORD-1004' AND p.sku = 'HD-003';"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT sku, stock FROM lab01.products ORDER BY sku;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "INSERT INTO lab01.order_items (order_id, product_id, quantity, unit_price) SELECT o.id, p.id, 10, p.unit_price FROM lab01.orders o, lab01.products p WHERE o.order_ref = 'ORD-1004' AND p.sku = 'ST-004';"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT sku, stock FROM lab01.products ORDER BY sku;"

The second insert (quantity 10 of ST-004, stock 8) is expected to fail and leave the stock unchanged.

OLTP and OLAP (read-only queries and `EXPLAIN ANALYZE`):

    type labs\lab01\db\tasks\oltp_olap.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

SQL injection (Python)

Python connects through `POSTGRES_PORT` in `.env`; change it (for example to 5433) and recreate the container if another PostgreSQL already uses port 5432. Docker commands run from the repository root; Python commands run from `labs\lab01\python` with `.venv` active.

    .venv\Scripts\activate.bat
    cd labs\lab01\python
    python connectivity_check.py

Step 1: run the vulnerable query. Start the program again for each input:

    python vulnerable_query.py

Inputs to type at the `Customer name:` prompt:

    Amina Hassan
    ' OR '1'='1
    x' UNION SELECT email, full_name FROM lab01.customers --

Expected: the first input returns only Amina's orders, the second returns every order, and the third returns customer e-mails and names from the customers table.

Step 2: after repairing `parameterized_query_starter.py`, run it with the same three inputs:

    python parameterized_query_starter.py

Expected: the first input still returns Amina's orders, and the second and third inputs return `[]`.
