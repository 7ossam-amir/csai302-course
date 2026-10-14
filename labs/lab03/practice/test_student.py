"""Public checks; complete student.py before running.

They need node1 and the object store running, and use only the test students below,
so your own lab03 rows and objects are not touched.
"""
import hashlib
import socket
import unittest
from pathlib import Path

from botocore.exceptions import ClientError

import student
from common import BUCKET, connect_db, s3_client

SCHEMA = Path(__file__).resolve().parents[1] / "large_objects" / "schema.sql"
TEST_STUDENTS = [9001, 90010]  # 'students/9001' is also a prefix of 'students/90010/'


def cleanup():
    s3 = s3_client()
    with connect_db() as conn:
        conn.execute("DELETE FROM lab03.documents WHERE student_id = ANY(%s)", (TEST_STUDENTS,))
        conn.execute("DELETE FROM lab03.students WHERE id = ANY(%s)", (TEST_STUDENTS,))
    for student_id in TEST_STUDENTS:
        listing = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"students/{student_id}/")
        for obj in listing.get("Contents", []):
            s3.delete_object(Bucket=BUCKET, Key=obj["Key"])


def add_document(conn, s3, student_id, name, data):
    """Store an object and its pointer row, like upload.py but with a predictable key."""
    key = f"students/{student_id}/{name}"
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType="text/plain")
    (doc_id,) = conn.execute(
        """INSERT INTO lab03.documents
               (student_id, file_name, content_type, size_bytes, sha256, bucket, object_key)
           VALUES (%s, %s, 'text/plain', %s, %s, %s, %s) RETURNING id""",
        (student_id, name, len(data), hashlib.sha256(data).hexdigest(), BUCKET, key),
    ).fetchone()
    conn.commit()
    return doc_id, key


def object_exists(s3, key):
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError:
        return False


class Lab03PracticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name, port in (("node1", 5434), ("objectstore", 9000)):  # fail fast, do not hang
            try:
                socket.create_connection(("127.0.0.1", port), timeout=3).close()
            except OSError:
                raise RuntimeError(f"{name} is not reachable on port {port}: start Docker Desktop "
                                   "and the lab services first (see the lab README)") from None
        try:
            with connect_db() as conn:
                conn.execute(SCHEMA.read_text())
            s3 = s3_client()
            if BUCKET not in [b["Name"] for b in s3.list_buckets()["Buckets"]]:
                s3.create_bucket(Bucket=BUCKET)
        except Exception as e:
            raise RuntimeError("start node1 and objectstore first (see the lab README)") from e

    def setUp(self):
        cleanup()
        self.s3 = s3_client()
        self.conn = connect_db()
        self.conn.execute(
            "INSERT INTO lab03.students VALUES (9001, 'Test A', 3.00, 'practice'),"
            " (90010, 'Test B', 3.00, 'practice')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        cleanup()

    def test_list_student_objects(self):
        self.assertEqual(student.list_student_objects(self.s3, BUCKET, 9001), [])
        add_document(self.conn, self.s3, 9001, "b.txt", b"12345")
        add_document(self.conn, self.s3, 9001, "a.txt", b"123")
        add_document(self.conn, self.s3, 90010, "other.txt", b"1")  # a different student
        self.assertEqual(
            student.list_student_objects(self.s3, BUCKET, 9001),
            [("students/9001/a.txt", 3), ("students/9001/b.txt", 5)],
        )

    def test_find_inconsistencies(self):
        prefix = "students/9001/"
        _, kept = add_document(self.conn, self.s3, 9001, "kept.txt", b"kept")
        _, lost = add_document(self.conn, self.s3, 9001, "lost.txt", b"lost")
        add_document(self.conn, self.s3, 90010, "other.txt", b"other")  # outside the prefix
        clean = {"missing_objects": [], "orphan_objects": []}
        self.assertEqual(student.find_inconsistencies(self.conn, self.s3, BUCKET, prefix), clean)

        self.s3.delete_object(Bucket=BUCKET, Key=lost)  # a row whose object is gone
        for name in ("z-orphan.txt", "a-orphan.txt"):  # objects that no row points to
            self.s3.put_object(Bucket=BUCKET, Key=prefix + name, Body=b"orphan")
        self.s3.delete_object(Bucket=BUCKET, Key="students/90010/other.txt")
        self.assertEqual(
            student.find_inconsistencies(self.conn, self.s3, BUCKET, prefix),
            {"missing_objects": [lost], "orphan_objects": [prefix + "a-orphan.txt",
                                                           prefix + "z-orphan.txt"]},
        )
        self.assertTrue(object_exists(self.s3, kept))  # the check only reads

    def test_delete_document(self):
        doc_id, key = add_document(self.conn, self.s3, 9001, "gone.txt", b"gone")
        other_id, other_key = add_document(self.conn, self.s3, 9001, "stays.txt", b"stays")
        self.assertIs(student.delete_document(self.conn, self.s3, doc_id), True)
        self.assertFalse(object_exists(self.s3, key))
        with connect_db() as fresh:  # a new connection sees only committed changes
            ids = [r[0] for r in fresh.execute(
                "SELECT id FROM lab03.documents WHERE student_id = 9001").fetchall()]
        self.assertEqual(ids, [other_id])
        self.assertTrue(object_exists(self.s3, other_key))
        self.assertIs(student.delete_document(self.conn, self.s3, doc_id), False)

    def test_tls_info(self):
        info = student.tls_info(self.conn)
        self.assertEqual(set(info), {"ssl", "version", "cipher"})
        self.assertIs(info["ssl"], True)
        self.assertTrue(info["version"].startswith("TLSv1."))
        self.assertTrue(info["cipher"])


if __name__ == "__main__":
    unittest.main()
