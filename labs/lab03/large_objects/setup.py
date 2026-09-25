"""Create the documents table and the bucket. Run once: python labs/lab03/large_objects/setup.py"""
from pathlib import Path

from common import BUCKET, connect_db, s3_client

schema = (Path(__file__).parent / "schema.sql").read_text()
with connect_db() as conn:
    conn.execute(schema)
print("table lab03.documents ready")

s3 = s3_client()
if BUCKET not in [b["Name"] for b in s3.list_buckets()["Buckets"]]:
    s3.create_bucket(Bucket=BUCKET)
print(f"bucket '{BUCKET}' ready")
