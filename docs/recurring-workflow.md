# Recurring lab workflow

The course environment is installed once and reused. Do not create a new virtual environment or PostgreSQL database for each lab.

Before a lab:

1. Pull the latest course materials with Git.
2. Activate the existing .venv.
3. Start PostgreSQL if it is stopped:

       docker compose --env-file .env -f infra/compose.yaml start postgres

   For the first run only, use the one-time setup guide's up command instead.
4. Check service health with docker compose --env-file .env -f infra/compose.yaml ps.
5. Connect to the csai302 database with DBeaver or psql.
6. Run that lab's SQL setup only if its schema is not already present.

During a lab, use the provided Python environment and connect through Psycopg. Use the SQL client to inspect the same data and observe database-side behavior.

To reset a lab, follow that lab's reset instructions. The normal reset is scoped to its schema and must leave other lab schemas intact. The course database and Docker volume remain in place.

After a lab, stop PostgreSQL if it is not needed. Stopping the container preserves the database for the next session. Commit and push coursework using the course's Git workflow.
