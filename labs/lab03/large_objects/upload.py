"""Upload a file: the bytes go to object storage, a small pointer row goes to PostgreSQL.

Usage: python labs/lab03/large_objects/upload.py <student_id> <file_path>
"""
import hashlib
import mimetypes
import sys
import uuid
from pathlib import Path

from common import BUCKET, connect_db, s3_client


def upload(student_id, file_path):
    path = Path(file_path)
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    key = f"students/{student_id}/{uuid.uuid4().hex}-{path.name}"  # unique, never overwrites

    s3 = s3_client()
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)  # 1. the big bytes
    try:
        with connect_db() as conn:  # 2. the small pointer row
            (doc_id,) = conn.execute(
                """INSERT INTO lab03.documents
                       (student_id, file_name, content_type, size_bytes, sha256, bucket, object_key)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (student_id, path.name, content_type, len(data), sha256, BUCKET, key),
            ).fetchone()
    except Exception:
        s3.delete_object(Bucket=BUCKET, Key=key)  # no row -> remove the object, so nothing is orphaned
        raise
    return doc_id, key, len(data)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    doc_id, key, size = upload(int(sys.argv[1]), sys.argv[2])
    print(f"document {doc_id}: {size:,} bytes stored at s3://{BUCKET}/{key}")
