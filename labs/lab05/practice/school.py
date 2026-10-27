"""Lab 5 Practice: a small school, its students and their course grades.

Usage (from the repository root):
  python labs/lab05/practice/school.py              # SQLite in memory, no server needed
  python labs/lab05/practice/school.py --postgres   # the shared course database

Read orm_demo.py first: each part below is the same idea, adapted to a school.
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import ForeignKey, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orm_demo import course_engine  # noqa: E402


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "practice05_students"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Enrollment(Base):
    """One student in one course: student_id points to practice05_students.id,
    course has at most 20 characters, grade is an integer."""
    __tablename__ = "practice05_enrollments"
    id: Mapped[int] = mapped_column(primary_key=True)
    # TODO: student_id, course and grade, like Order in orm_demo.py.


PERMISSIONS = {"student": {"read"}, "teacher": {"read", "report"},
               "registrar": {"read", "report", "write"}}

STUDENTS = [(1, "Sara"), (2, "Omar"), (3, "Laila")]
# (student_id, course, grade); the enrollment ids become 1..5 in this order
ENROLLMENTS = [(1, "CSAI302", 85), (1, "CSAI201", 62), (2, "CSAI302", 91),
               (3, "CSAI302", 48), (3, "CSAI201", 77)]


class SchoolService:
    """Role must come from trusted authentication, never from the user's input."""
    def __init__(self, session, role):
        self.session, self.role = session, role

    def authorize(self, action):
        """Raise PermissionError unless this role may perform the action."""
        # TODO: look the role up in PERMISSIONS; an unknown role may do nothing.
        raise NotImplementedError

    def find_student(self, name):
        """'read': return the Student objects with exactly this name, using an ORM select."""
        # TODO: authorize first, then select(Student).where(...).
        raise NotImplementedError

    def top_grades(self, minimum):
        """'report': return [(name, course, grade), ...] with grade >= minimum, ordered by
        enrollment id. Use text() with a bound :minimum parameter."""
        # TODO: JOIN the two tables; never put minimum inside the SQL string.
        raise NotImplementedError

    def add_enrollment(self, student_id, course, grade):
        """'write': add one enrollment, flush (do not commit) and return its new id.
        Raise ValueError if the grade is not between 0 and 100."""
        # TODO: authorize, check the grade, session.add, session.flush, return the id.
        raise NotImplementedError


def seed(engine):
    """Create both tables, then insert STUDENTS and ENROLLMENTS only if no student exists yet."""
    # TODO: like seed() in orm_demo.py; let the database choose the enrollment ids.
    raise NotImplementedError


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    engine = course_engine() if args.postgres else create_engine("sqlite:///:memory:")
    seed(engine)
    with Session(engine) as session:
        student = SchoolService(session, "student")
        print("Lookup:", [s.name for s in student.find_student("Sara")])
        print("Injection input returns:", student.find_student("' OR 1=1 --"))
        print("Grades >= 80:", SchoolService(session, "teacher").top_grades(80))
        try:
            student.top_grades(0)
        except PermissionError as error:
            print("Access denied:", error)
        print("New enrollment id:", SchoolService(session, "registrar").add_enrollment(2, "CSAI201", 70))
        session.rollback()  # demo only: the new enrollment is not kept
