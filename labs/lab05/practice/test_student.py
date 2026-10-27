"""Public checks; complete school.py and operators.py before running.

The database checks use a fresh SQLite database in memory, so no server is needed
and the course database is not touched.
"""
import unittest

import numpy as np
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import school
from operators import (Scan, Filter, Project, Limit, collect, VectorScan, VectorFilter,
                       VectorProject, collect_batches, hash_join)

ROWS = [{"id": i, "grade": (i * 37) % 101} for i in range(30)]


def batches(operator):
    operator.open()
    try:
        result = []
        while (batch := operator.next_batch()) is not None:
            result.append(batch)
        return result
    finally:
        operator.close()


class CountingScan(Scan):
    def open(self):
        super().open()
        self.calls = 0

    def next(self):
        self.calls += 1
        return super().next()


class SchoolTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        school.seed(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def count(self, model):
        return self.session.scalar(select(func.count()).select_from(model))

    def test_enrollment_columns(self):
        columns = school.Enrollment.__table__.columns
        self.assertTrue({"id", "student_id", "course", "grade"} <= set(columns.keys()))
        self.assertEqual([fk.target_fullname for fk in columns["student_id"].foreign_keys],
                         ["practice05_students.id"])
        self.assertEqual(columns["course"].type.length, 20)

    def test_seed_runs_twice(self):
        school.seed(self.engine)
        self.assertEqual((self.count(school.Student), self.count(school.Enrollment)), (3, 5))

    def test_find_student_binds_the_name(self):
        service = school.SchoolService(self.session, "student")
        self.assertEqual([s.id for s in service.find_student("Sara")], [1])
        self.assertEqual(service.find_student("' OR 1=1 --"), [])
        self.assertEqual(service.find_student("sara"), [])

    def test_top_grades_binds_the_minimum(self):
        service = school.SchoolService(self.session, "teacher")
        self.assertEqual([tuple(r) for r in service.top_grades(80)],
                         [("Sara", "CSAI302", 85), ("Omar", "CSAI302", 91)])
        self.assertEqual(len(service.top_grades(0)), 5)
        self.assertEqual(service.top_grades("0 OR 1=1"), [])

    def test_permissions(self):
        for role in ("student", "nobody"):
            service = school.SchoolService(self.session, role)
            with self.assertRaises(PermissionError):
                service.top_grades(0)
            with self.assertRaises(PermissionError):
                service.add_enrollment(1, "CSAI101", 50)
        with self.assertRaises(PermissionError):
            school.SchoolService(self.session, "nobody").find_student("Sara")
        with self.assertRaises(PermissionError):
            school.SchoolService(self.session, "teacher").add_enrollment(1, "CSAI101", 50)
        self.assertEqual(self.count(school.Enrollment), 5)

    def test_add_enrollment_and_rollback(self):
        registrar = school.SchoolService(self.session, "registrar")
        for bad in (-1, 101):
            with self.assertRaises(ValueError):
                registrar.add_enrollment(1, "CSAI101", bad)
        new_id = registrar.add_enrollment(2, "CSAI201", 70)
        self.assertEqual(new_id, 6)
        self.assertEqual(self.count(school.Enrollment), 6)
        self.session.rollback()
        self.assertEqual(self.count(school.Enrollment), 5)


class VolcanoTests(unittest.TestCase):
    def test_filter_and_project(self):
        tree = Project(Filter(Scan(ROWS), lambda r: r["grade"] >= 90), ["id"])
        expected = [{"id": r["id"]} for r in ROWS if r["grade"] >= 90]
        self.assertEqual(collect(tree), expected)
        self.assertEqual(collect(tree), expected)  # reopening starts again
        self.assertEqual(collect(Filter(Scan(ROWS), lambda r: False)), [])
        self.assertEqual(collect(Project(Scan([]), ["id"])), [])

    def test_limit_stops_early(self):
        scan = CountingScan(ROWS)
        self.assertEqual(collect(Limit(scan, 3)), ROWS[:3])
        self.assertEqual(scan.calls, 3)
        self.assertEqual(collect(Limit(Scan(ROWS), 100)), ROWS)
        self.assertEqual(collect(Limit(Scan(ROWS), 0)), [])
        top = [r for r in ROWS if r["grade"] >= 90][:2]
        tree = Limit(Filter(Scan(ROWS), lambda r: r["grade"] >= 90), 2)
        self.assertEqual(collect(tree), top)
        self.assertEqual(collect(tree), top)  # reopening resets the count
        with self.assertRaises(ValueError):
            Limit(Scan(ROWS), -1)


class VectorTests(unittest.TestCase):
    def tree(self, size):
        columns = {"id": [r["id"] for r in ROWS], "grade": [r["grade"] for r in ROWS]}
        return VectorProject(VectorFilter(VectorScan(columns, size),
                                          lambda b: b["grade"] >= 90), ["id"])

    def test_same_result_as_volcano(self):
        expected = collect(Project(Filter(Scan(ROWS), lambda r: r["grade"] >= 90), ["id"]))
        for size in (1, 4, 7, 100):
            self.assertEqual(collect_batches(self.tree(size)), expected)
            self.assertEqual(collect_batches(self.tree(size)), expected)

    def test_no_empty_batches(self):
        for size in (1, 4):
            self.assertTrue(all(len(b["id"]) > 0 for b in batches(self.tree(size))))
        self.assertEqual(set(batches(self.tree(4))[0]), {"id"})
        self.assertEqual(collect_batches(VectorFilter(VectorScan({"id": [1, 2]}),
                                                      lambda b: b["id"] > 5)), [])

    def test_bad_predicate(self):
        for predicate in (lambda b: b["id"], lambda b: True, lambda b: b["id"][:1] > 0):
            with self.assertRaises(ValueError):
                collect_batches(VectorFilter(VectorScan({"id": [1, 2]}), predicate))


class HashJoinTests(unittest.TestCase):
    def test_against_nested_loop(self):
        rng = np.random.default_rng(302)
        cases = [([], []), ([], [1]), ([3, 3], [3, 3, 4]), ([-1, 15, 31], [15, -1, 31, 47]),
                 (rng.integers(-30, 30, 120), rng.integers(-30, 30, 90))]
        for left, right in cases:
            expected = sorted((i, j) for i, a in enumerate(left)
                              for j, b in enumerate(right) if a == b)
            for buckets in (1, 4, 16):
                result = hash_join(left, right, buckets)
                self.assertEqual(sorted(result), expected)
                self.assertTrue(all(type(i) is int and type(j) is int for i, j in result))

    def test_bad_bucket_count(self):
        with self.assertRaises(ValueError):
            hash_join([1], [1], 0)


if __name__ == "__main__":
    unittest.main()
