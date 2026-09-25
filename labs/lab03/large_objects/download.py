"""Find a document in PostgreSQL, then fetch its bytes from object storage.

Usage:
  python labs/lab03/large_objects/download.py                 list all documents
  python labs/lab03/large_objects/download.py <document_id>   download one into downloads/
"""
import hashlib
import sys
from pathlib import Path

from common import connect_db, s3_client

OUT_DIR = Path(__file__).parent / "downloads"


def list_documents():
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT d.id, s.name, d.file_name, d.size_bytes, d.object_key
               FROM lab03.documents d JOIN lab03.students s ON s.id = d.student_id
               ORDER BY d.id"""
        ).fetchall()
    print(f"{'id':>3}  {'student':<8} {'file':<24} {'bytes':>10}  object_key")
    for doc_id, student, name, size, key in rows:
        print(f"{doc_id:>3}  {student:<8} {name:<24} {size:>10,}  {key}")


def download(doc_id):
    with connect_db() as conn:  # 1. ask PostgreSQL where the file is
        row = conn.execute(
            "SELECT file_name, bucket, object_key, sha256 FROM lab03.documents WHERE id = %s",
            (doc_id,),
        ).fetchone()
    if row is None:
        sys.exit(f"no document with id {doc_id}")
    file_name, bucket, key, sha256 = row

    data = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()  # 2. fetch the bytes
    if hashlib.sha256(data).hexdigest() != sha256:  # 3. same fingerprint as when uploaded?
        sys.exit("checksum mismatch: the object changed after upload")

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / file_name
    out.write_bytes(data)
    print(f"downloaded {len(data):,} bytes from s3://{bucket}/{key}")
    print(f"checksum OK, saved to {out}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        list_documents()
    else:
        download(int(sys.argv[1]))
