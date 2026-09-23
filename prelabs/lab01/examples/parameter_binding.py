"""Small example: a supplied value stays data, even if it contains SQL syntax."""

from labs.lab01.python.db import connect


untrusted_text = "O'Brien; DROP TABLE students; --"

with connect() as connection:
    row = connection.execute(
        "SELECT %s::text AS supplied_text",
        (untrusted_text,),
    ).fetchone()

print(row[0])
