# One-time environment setup

Complete this before Lab 1. The instructions use a host Python virtual environment and a PostgreSQL server in Docker Compose.

## Required tools

- Git
- Docker Desktop on Windows or macOS, or Docker Engine with Compose on Linux
- Python 3.12
- DBeaver Community or another PostgreSQL client is optional; psql is available inside the PostgreSQL container

Psycopg 3.3 supports Python 3.10 and newer on Windows, macOS, and Linux. This course standardizes on Python 3.12 so students use the same runtime.

## Configure the local environment

From the course repository root, create a local environment file.

PowerShell:

    Copy-Item .env.example .env

macOS or Linux:

    cp .env.example .env

The sample values are for local coursework only. Keep .env private; it is excluded from Git.

## Create the Python virtual environment

PowerShell:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

macOS or Linux:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

The .venv directory is shared by the course and is not committed to Git. Activate it again when opening a new terminal.

## Start and verify PostgreSQL

Start the service from the repository root:

    docker compose --env-file .env -f infra/compose.yaml up -d postgres

Wait until the service reports healthy:

    docker compose --env-file .env -f infra/compose.yaml ps

Check a SQL connection from inside the container:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT current_database(), version();"

Open an interactive PostgreSQL shell when you need to inspect the database directly:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302

If you changed the local database name or username in .env, use those values in the psql command.

## Create and inspect Lab 1 objects

From the repository root, run the schema and sample data files once. In PowerShell:

    Get-Content .\labs\lab01\db\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302
    Get-Content .\labs\lab01\db\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302

On macOS or Linux:

    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab01/db/schema.sql
    docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U csai302 -d csai302 < labs/lab01/db/seed.sql

List the Lab 1 tables and inspect sample rows:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "\dt lab01.*"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT * FROM lab01.customers;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT * FROM lab01.orders;"

## Connect from DBeaver

Create a PostgreSQL connection with these local defaults:

- Host: localhost
- Port: 5432
- Database: csai302
- Username: csai302
- Password: the value in .env

If port 5432 is already in use, change POSTGRES_PORT in .env and use that port in DBeaver and the Python connection.

## Test Python connectivity

With the virtual environment active and PostgreSQL healthy, run:

    python labs/lab01/python/connectivity_check.py

The script reports the connected database, user, and PostgreSQL version.
