# Shared infrastructure

The default stack is one PostgreSQL 17.11 server, started by infra/compose.yaml. It creates the csai302 database on the first start and stores its data in the named Docker volume csai302-postgres-data.

Run Compose commands from the course repository root so Compose reads the root .env file. Copy .env.example to .env before starting the service.

The database and volume are shared by the course. Lab setup and reset files must operate only on that lab's schema. Add another service only when a lab's scope requires it, and make it opt-in so the baseline remains PostgreSQL alone.

## Useful commands

Start PostgreSQL:

    docker compose --env-file .env -f infra/compose.yaml up -d postgres

Check service state and health:

    docker compose --env-file .env -f infra/compose.yaml ps

Read PostgreSQL logs:

    docker compose --env-file .env -f infra/compose.yaml logs -f postgres

Open psql inside the container, using the local values in .env.example:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302

Stop the container while preserving its data:

    docker compose --env-file .env -f infra/compose.yaml stop postgres

Starting the service again uses the same container configuration and named volume. Do not use volume-removal commands for a normal lab reset: they erase the entire course database.

## Client connection

From DBeaver or a host-installed psql client, connect to localhost on the port in .env. The database is csai302. Use the username and password from .env.
