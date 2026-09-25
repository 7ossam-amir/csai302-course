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

macOS or Linux:

    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/schema.sql

Repeat with seed.sql. Substitute values from .env if you changed the local username or database name.

## Reset Lab 1 data

Only run this when you intend to discard Lab 1 objects. Execute db/reset.sql, then db/schema.sql, then db/seed.sql. This drops only schema lab01; it does not recreate the course database or remove the Docker volume.

## Run commands (function, procedure, trigger)

Open psql inside the container:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302

Load the task files (PowerShell):

    Get-Content labs/lab01/db/schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    Get-Content labs/lab01/db/seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    Get-Content labs/lab01/db/tasks/function.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    Get-Content labs/lab01/db/tasks/procedure.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    Get-Content labs/lab01/db/tasks/trigger.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

Load the task files (macOS or Linux):

    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/schema.sql
    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/seed.sql
    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/tasks/function.sql
    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/tasks/procedure.sql
    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302 < labs/lab01/db/tasks/trigger.sql

### Function

    SELECT lab01.calculate_order_total(1);

    SELECT order_ref, lab01.calculate_order_total(id) AS total
    FROM lab01.orders
    ORDER BY id;

    SELECT lab01.calculate_order_total(999);

### Procedure

    CALL lab01.count_pending_orders();

    SELECT id, order_ref, status FROM lab01.orders WHERE id = 1;
    CALL lab01.update_order_status(1, 'paid');
    SELECT id, order_ref, status FROM lab01.orders WHERE id = 1;

    CALL lab01.update_order_status(999, 'paid');

    CALL lab01.get_order_summary(1, NULL, NULL);

### Trigger

    SELECT id, sku, stock FROM lab01.products ORDER BY id;

    INSERT INTO lab01.order_items (order_id, product_id, quantity, unit_price)
    SELECT o.id, p.id, 2, p.unit_price
    FROM lab01.orders o, lab01.products p
    WHERE o.order_ref = 'ORD-1004' AND p.sku = 'KB-001';

    SELECT id, sku, stock FROM lab01.products ORDER BY id;

    INSERT INTO lab01.order_items (order_id, product_id, quantity, unit_price)
    SELECT o.id, p.id, 100, p.unit_price
    FROM lab01.orders o, lab01.products p
    WHERE o.order_ref = 'ORD-1004' AND p.sku = 'HD-003';

    SELECT id, sku, stock FROM lab01.products ORDER BY id;

### Verify objects exist

    \df lab01.*
    SELECT tgname FROM pg_trigger WHERE tgrelid = 'lab01.order_items'::regclass AND NOT tgisinternal;

## Run commands (Windows Command Prompt)

Run these from the repository root.

Start PostgreSQL and check it:

    docker compose --env-file .env -f infra/compose.yaml up -d postgres
    docker compose --env-file .env -f infra/compose.yaml ps

Load the schema, seed, and task files:

    type labs\lab01\db\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\tasks\function.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\tasks\procedure.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\tasks\trigger.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

Run a single statement:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT order_ref, lab01.calculate_order_total(id) AS total FROM lab01.orders ORDER BY id;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.count_pending_orders();"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.update_order_status(1, 'paid');"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL lab01.get_order_summary(1, NULL, NULL);"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT sku, stock FROM lab01.products ORDER BY sku;"

## Run commands: OLTP and OLAP

Load and run `db/tasks/oltp_olap.sql` (read-only queries and EXPLAIN ANALYZE):

    type labs\lab01\db\tasks\oltp_olap.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

## Run commands: Python (SQL injection)

With `.venv` active, run from `labs\lab01\python`. Python connects through the `POSTGRES_PORT` in `.env`; change it (for example to 5433) if another PostgreSQL already uses 5432.

    .venv\Scripts\activate.bat
    cd labs\lab01\python
    python connectivity_check.py
    python vulnerable_query.py
    python parameterized_query_starter.py

Inputs to try at the `Customer name:` prompt:

    Amina Hassan
    ' OR '1'='1
    x' UNION SELECT email, full_name FROM lab01.customers --
