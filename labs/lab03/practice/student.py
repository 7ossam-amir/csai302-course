"""Lab 3 Practice: use the lab's object store and its TLS connection to PostgreSQL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "large_objects"))
from common import BUCKET, connect_db, s3_client  # noqa: E402,F401  (for experiment.py)


def tls_info(conn):
    """Return {'ssl': ..., 'version': ..., 'cipher': ...} for this connection.

    Example result: {'ssl': True, 'version': 'TLSv1.3', 'cipher': 'TLS_AES_256_GCM_SHA384'}
    """
    # TODO: run this query and fetch its single row:
    #   SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()
    # TODO: return the three values in a dictionary.
    raise NotImplementedError


def list_student_objects(s3, bucket, student_id):
    """Return [(key, size_bytes), ...] for one student's objects, sorted by key.

    Example for student 5: [('students/5/aa11-notes.txt', 120), ('students/5/bb22-lab.pdf', 9000)]
    """
    prefix = f"students/{student_id}/"
    # TODO: response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    # TODO: response.get("Contents", []) is a list of dicts with "Key" and "Size".
    # TODO: return a sorted list of (key, size) tuples.
    raise NotImplementedError


def delete_document(conn, s3, doc_id):
    """Delete a document from PostgreSQL and from the object store.
    Return True if the document existed, False if there is no such id.
    """
    # TODO: SELECT bucket, object_key FROM lab03.documents WHERE id = %s
    #       If fetchone() returns None, return False.
    # TODO: DELETE FROM lab03.documents WHERE id = %s, then conn.commit().
    # TODO: only after the commit: s3.delete_object(Bucket=..., Key=...), then return True.
    raise NotImplementedError


def find_inconsistencies(conn, s3, bucket, prefix):
    """Compare lab03.documents with the object store, for keys starting with prefix.
    Return {'missing_objects': [...], 'orphan_objects': [...]}, both sorted lists of keys.

      missing_objects: PostgreSQL has a row for the key, but the object store has no such object.
      orphan_objects:  the object store has the object, but no row points to it.
    """
    # TODO: keys in PostgreSQL, as a set:
    #   SELECT object_key FROM lab03.documents
    #   WHERE bucket = %s AND starts_with(object_key, %s)
    # TODO: keys in the object store, as a set (list_objects_v2 with Prefix=prefix).
    # TODO: use set difference (a - b) for each list, and return them sorted.
    raise NotImplementedError
