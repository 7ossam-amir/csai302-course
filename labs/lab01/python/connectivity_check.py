from db import connect


with connect() as connection:
    row = connection.execute(
        "SELECT current_database(), current_user, version()"
    ).fetchone()

print(f"Connected to database: {row[0]}")
print(f"Connected as: {row[1]}")
print(row[2])
