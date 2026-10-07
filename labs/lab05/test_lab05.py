import unittest
import numpy as np
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from executors import *
from orm_demo import QueryService, Order, seed


class ExecutorsTest(unittest.TestCase):
    def test_join_against_nested_loop(self):
        rng = np.random.default_rng(5)
        for left, right in [([], []), ([1, 1], [1, 1, 2]), ([-1, 255], [255, -1]),
                            (rng.integers(-20, 20, 150), rng.integers(-20, 20, 100))]:
            expected = sorted((i, j) for i, a in enumerate(left)
                              for j, b in enumerate(right) if a == b)
            self.assertEqual(sorted(scalar_hash_join(left, right)), expected)
            for buckets in (1, 7, 256):
                self.assertEqual(sorted(simd_hash_join(left, right, buckets)), expected)

    def test_pipelines_and_reopen(self):
        rows = [{"id": i, "amount": i * 10} for i in range(17)]
        volcano = Project(Filter(Scan(rows), lambda r: r["amount"] >= 80), ["id"])
        expected = [{"id": i} for i in range(8, 17)]
        self.assertEqual(collect(volcano), expected)
        self.assertEqual(collect(volcano), expected)
        for size in (1, 4, 100):
            vector = VectorProject(VectorFilter(VectorScan(
                {"id": np.arange(17), "amount": np.arange(17) * 10}, size),
                lambda b: b["amount"] >= 80), ["id"])
            self.assertEqual(collect_batches(vector), expected)
            self.assertEqual(collect_batches(vector), expected)

    def test_empty_and_no_matches(self):
        self.assertEqual(collect(Filter(Scan([]), lambda r: True)), [])
        self.assertEqual(collect_batches(VectorScan({"id": []})), [])
        self.assertEqual(collect_batches(VectorFilter(VectorScan({"id": [1, 2]}),
                                                     lambda b: b["id"] > 100)), [])
        with self.assertRaises(ValueError):
            VectorScan({"id": [1]}, 0)
        with self.assertRaises(ValueError):
            VectorScan({"id": [1], "amount": []})


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        seed(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_parameter_binding(self):
        viewer = QueryService(self.session, "viewer")
        self.assertEqual(len(viewer.find_customer("Mona")), 1)
        self.assertEqual(viewer.find_customer("' OR 1=1 --"), [])
        analyst = QueryService(self.session, "analyst")
        self.assertEqual(len(analyst.report(200)), 2)
        self.assertEqual(analyst.report("0 OR 1=1"), [])

    def test_permissions_and_write(self):
        for role in ("viewer", "unknown"):
            service = QueryService(self.session, role)
            with self.assertRaises(PermissionError):
                service.report(0)
            with self.assertRaises(PermissionError):
                service.add_order(1, 50)
        with self.assertRaises(PermissionError):
            QueryService(self.session, "unknown").find_customer("Mona")
        with self.assertRaises(PermissionError):
            QueryService(self.session, "analyst").add_order(1, 50)
        admin = QueryService(self.session, "admin")
        admin.add_order(1, 50)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Order)), 4)
        self.session.rollback()
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Order)), 3)


if __name__ == "__main__":
    unittest.main()
