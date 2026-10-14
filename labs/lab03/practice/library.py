"""Lab 3 Practice: a small library that keeps book files in object storage.

Usage (from the repository root):
  python labs/lab03/practice/library.py setup
  python labs/lab03/practice/library.py upload <book_id> <file_path>
  python labs/lab03/practice/library.py list <book_id>
  python labs/lab03/practice/library.py download <file_id>
  python labs/lab03/practice/library.py tls

Read large_objects/setup.py, upload.py and download.py first: each function below is the
same idea, adapted to books.
"""
import hashlib
import mimetypes
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "large_objects"))
from common import connect_db, s3_client  # noqa: E402

BUCKET = "practice03"
SCHEMA = Path(__file__).parent / "schema.sql"
OUT_DIR = Path(__file__).parent / "downloads"


def setup():
    """Run schema.sql on the database and create the bucket if it does not exist."""
    # TODO: like large_objects/setup.py, but with this file's SCHEMA and BUCKET.
    raise NotImplementedError


def upload_file(book_id, file_path):
    """Store the file's bytes in BUCKET and a pointer row in practice03.book_files.
    The key is books/<book_id>/<uuid>-<file name>. Return (file_id, key).
    If the INSERT fails, delete the object again and re-raise the error.
    """
    path = Path(file_path)
    data = path.read_bytes()
    # TODO: sha256 fingerprint, content type, and the key.
    # TODO: put_object first, then INSERT ... RETURNING id inside try/except.
    raise NotImplementedError


def list_files(book_id):
    """Return [(file_id, file_name, size_bytes), ...] for one book, ordered by file_id."""
    # TODO: one SELECT on practice03.book_files.
    raise NotImplementedError


def download_file(file_id):
    """Look up the file in PostgreSQL, fetch it from object storage, verify it, and save it
    as OUT_DIR / file_name. Return the saved path, or None if there is no such file_id.
    Raise ValueError if the fingerprint does not match.
    """
    # TODO: SELECT file_name, bucket, object_key, sha256 ...
    # TODO: get_object, compare the sha256, write the bytes, return the path.
    raise NotImplementedError


def tls_info():
    """Return {'ssl': ..., 'version': ..., 'cipher': ...} for a connection from connect_db()."""
    # TODO: SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()
    raise NotImplementedError


if __name__ == "__main__":
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if command == "setup":
        setup()
        print(f"tables practice03.* and bucket '{BUCKET}' ready")
    elif command == "upload" and len(args) == 2:
        file_id, key = upload_file(int(args[0]), args[1])
        print(f"file {file_id} stored at s3://{BUCKET}/{key}")
    elif command == "list" and len(args) == 1:
        for file_id, name, size in list_files(int(args[0])):
            print(f"{file_id:>4}  {name:<30} {size:>10,} bytes")
    elif command == "download" and len(args) == 1:
        out = download_file(int(args[0]))
        print(f"no file with id {args[0]}" if out is None else f"checksum OK, saved to {out}")
    elif command == "tls":
        print(tls_info())
    else:
        sys.exit(__doc__)
