# CSAI 302 — Advanced Database Systems

Student-facing course materials and reproducible lab infrastructure.

The course uses one PostgreSQL service, one persistent database, and one Python environment for the semester. Labs add their own schema to the shared database; students do not reinstall PostgreSQL or create a new database for every lab.

## Install once

### Prerequisites

- Git
- Docker Desktop on Windows or macOS, or Docker Engine with Compose on Linux
- Python 3.12
- DBeaver Community or another PostgreSQL client is optional

Install Docker and Python from their official sources, and make sure Docker is running before starting the database.

### Get the course files

If you have not cloned the repository yet:

```sh
git clone https://github.com/7ossam-amir/csai302-course.git
cd csai302-course
```

If you already have it, open a terminal in the repository folder instead.

### Configure the local environment and Python

Create the local settings file. It contains coursework-only database settings and is excluded from Git.

PowerShell:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS or Linux:

```sh
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Activate `.venv` again whenever you open a new terminal. If your system uses a different Python command, use the command that starts Python 3.12.

### Start PostgreSQL for the first time

From the repository root, create and start the shared database service:

```sh
docker compose -f infra/compose.yaml up -d postgres
docker compose -f infra/compose.yaml ps
```

The service may take a short time to become healthy. Verify it from the container:

```sh
docker compose -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT current_database(), version();"
```

Then, with `.venv` active, verify Python can connect:

```sh
python labs/lab01/python/connectivity_check.py
```

The default local connection is host `localhost`, port `5432`, database `csai302`, username `csai302`, and the password in `.env`. See [the full setup guide](docs/environment-setup.md) for DBeaver configuration and troubleshooting.

## Use it for each lab

After the one-time setup, reuse the same environment. Do not make a new virtual environment or PostgreSQL database for each lab.

1. Get the latest course files:

   ```sh
   git pull
   ```

2. Activate the existing Python environment:

   PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   macOS or Linux:

   ```sh
   source .venv/bin/activate
   ```

3. Start PostgreSQL if it is stopped. After the first-time `up` command above, use:

   ```sh
   docker compose -f infra/compose.yaml start postgres
   docker compose -f infra/compose.yaml ps
   ```

   If the service has not yet been created on this computer, use the first-time `up -d postgres` command instead.

4. Read the matching `prelabs/labNN/README.md` before class and `labs/labNN/README.md` during the lab. Follow that lab's instructions for its SQL setup, Python exercises, and any schema-scoped reset.

5. Use the same PostgreSQL service throughout the lab. You can connect with DBeaver, or run the course's Python examples from the active `.venv`.

When finished, stop the service if you do not need it:

```sh
docker compose -f infra/compose.yaml stop postgres
```

Stopping PostgreSQL preserves the database for next time. Do not remove the shared Docker volume as part of routine work; reset only the schema specified by that lab's instructions.

## Repository map

- `docs/` — one-time setup and recurring workflow.
- `infra/` — the shared PostgreSQL Compose service.
- `prelabs/` — preparation guides and small conceptual examples.
- `labs/` — live-lab guides, starter files, and lab-specific database objects.
- `project/` — project guidance and milestone briefs as they are developed.

Optional practice challenges belong with the related live lab. Shared code or datasets should be added only when more than one lab genuinely reuses them.

## Course project

Project briefs live here; each student team keeps its implementation in its own Git repository. Instructor solutions and grading notes belong in a separate private staff repository.
