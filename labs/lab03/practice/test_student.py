"""Public checks; complete schema.sql and library.py before running.

They need node1 and the object store running, and use only book 9001 (and the unused id
999999), so your own practice03 rows and files are not touched.
"""
import hashlib
import socket
import tempfile
import unittest
from pathlib import Path

from botocore.exceptions import ClientError

import library
from library import BUCKET, connect_db, s3_client

TEST_BOOK = 9001
MISSING_BOOK = 999999
TEST_NAME = "practice-test-9001.txt"


def cleanup():
    s3 = s3_client()
    with connect_db() as conn:
        conn.execute("DELETE FROM practice03.book_files WHERE book_id = %s", (TEST_BOOK,))
        conn.execute("DELETE FROM practice03.books WHERE id = %s", (TEST_BOOK,))
    for book_id in (TEST_BOOK, MISSING_BOOK):
        listing = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"books/{book_id}/")
        for obj in listing.get("Contents", []):
            s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
    (library.OUT_DIR / TEST_NAME).unlink(missing_ok=True)


class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name, port in (("node1", 5434), ("objectstore", 9000)):  # fail fast, do not hang
            try:
                socket.create_connection(("127.0.0.1", port), timeout=3).close()
            except OSError:
                raise RuntimeError(f"{name} is not reachable on port {port}: start Docker Desktop "
                                   "and the lab services first (see the lab README)") from None
        library.setup()
        library.setup()  # running it twice must also work

    def setUp(self):
        cleanup()
        self.s3 = s3_client()
        with connect_db() as conn:
            conn.execute("INSERT INTO practice03.books (id, title, author, written_by)"
                         " VALUES (%s, 'Test Book', 'Tester', 'node1')", (TEST_BOOK,))
        self.folder = tempfile.TemporaryDirectory()
        self.file = Path(self.folder.name) / TEST_NAME
        self.data = b"chapter 1: shared disk\n" * 100
        self.file.write_bytes(self.data)

    def tearDown(self):
        self.folder.cleanup()
        cleanup()

    def test_bucket_and_tables_exist(self):
        self.assertIn(BUCKET, [b["Name"] for b in self.s3.list_buckets()["Buckets"]])
        with connect_db() as conn:
            columns = {r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'practice03' AND table_name = 'book_files'").fetchall()}
        self.assertTrue({"book_id", "file_name", "content_type", "size_bytes", "sha256",
                         "bucket", "object_key", "uploaded_at"} <= columns)

    def test_upload_stores_bytes_and_pointer(self):
        file_id, key = library.upload_file(TEST_BOOK, self.file)
        self.assertTrue(key.startswith(f"books/{TEST_BOOK}/"))
        self.assertTrue(key.endswith("-" + TEST_NAME))
        stored = self.s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        self.assertEqual(stored, self.data)
        with connect_db() as conn:
            row = conn.execute(
                "SELECT book_id, file_name, size_bytes, sha256, bucket, object_key"
                " FROM practice03.book_files WHERE id = %s", (file_id,)).fetchone()
        self.assertEqual(row, (TEST_BOOK, TEST_NAME, len(self.data),
                               hashlib.sha256(self.data).hexdigest(), BUCKET, key))

    def test_same_name_twice_does_not_overwrite(self):
        _, first = library.upload_file(TEST_BOOK, self.file)
        _, second = library.upload_file(TEST_BOOK, self.file)
        self.assertNotEqual(first, second)

    def test_unknown_book_leaves_no_object(self):
        with self.assertRaises(Exception):
            library.upload_file(MISSING_BOOK, self.file)
        listing = self.s3.list_objects_v2(Bucket=BUCKET, Prefix=f"books/{MISSING_BOOK}/")
        self.assertEqual(listing.get("Contents", []), [])

    def test_list_files(self):
        self.assertEqual(library.list_files(TEST_BOOK), [])
        first, _ = library.upload_file(TEST_BOOK, self.file)
        second, _ = library.upload_file(TEST_BOOK, self.file)
        self.assertEqual(library.list_files(TEST_BOOK), [(first, TEST_NAME, len(self.data)),
                                                         (second, TEST_NAME, len(self.data))])

    def test_download_verifies_the_file(self):
        file_id, key = library.upload_file(TEST_BOOK, self.file)
        out = library.download_file(file_id)
        self.assertEqual(Path(out), library.OUT_DIR / TEST_NAME)
        self.assertEqual(Path(out).read_bytes(), self.data)
        self.assertIsNone(library.download_file(-1))
        self.s3.put_object(Bucket=BUCKET, Key=key, Body=b"changed behind our back")
        with self.assertRaises(ValueError):
            library.download_file(file_id)

    def test_tls_info(self):
        info = library.tls_info()
        self.assertEqual(set(info), {"ssl", "version", "cipher"})
        self.assertIs(info["ssl"], True)
        self.assertTrue(info["version"].startswith("TLSv1."))


if __name__ == "__main__":
    unittest.main()
