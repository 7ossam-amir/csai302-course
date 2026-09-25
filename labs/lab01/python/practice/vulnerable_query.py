"""Intentionally vulnerable example for local teaching only."""

from db import connect


def find_enrollments_by_student_name(name: str) -> list[tuple]:
    # Deliberately unsafe: input is inserted into the SQL instructions.
    query = f"""
        SELECT c.course_code, e.status
        FROM practice01.enrollments AS e
        JOIN practice01.students AS s ON s.id = e.student_id
        JOIN practice01.courses AS c ON c.id = e.course_id
        WHERE s.full_name = '{name}'
    """
    with connect() as connection:
        return connection.execute(query).fetchall()


if __name__ == "__main__":
    supplied_name = input("Student name: ")
    print(find_enrollments_by_student_name(supplied_name))
