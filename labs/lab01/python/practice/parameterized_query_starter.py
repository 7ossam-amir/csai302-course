"""Student starter: repair the vulnerable student-name query."""

from db import connect


def find_enrollments_by_student_name(name: str) -> list[tuple]:
    # TODO: Keep the SQL statement fixed and pass name as a bound value.
    query = """
        SELECT c.course_code, e.status
        FROM practice01.enrollments AS e
        JOIN practice01.students AS s ON s.id = e.student_id
        JOIN practice01.courses AS c ON c.id = e.course_id
        WHERE c.full_name = %s
    """
    # TODO: Supply the value separately using Psycopg's parameter binding.
    parameters = (name,)

    with connect() as connection:
        return connection.execute(query, parameters).fetchall()


if __name__ == "__main__":
    supplied_name = input("Student name: ")
    print(find_enrollments_by_student_name(supplied_name))
