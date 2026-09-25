"""The basic S3 API operations against the local object store (RustFS, S3-compatible).

Run from the repository root: python labs/lab03/object_storage/s3_basics.py
"""
import urllib.request

import boto3
from botocore.config import Config

BUCKET = "lab03"

# 1. Connect: the same code works with Amazon S3, MinIO or RustFS; only endpoint_url changes.
s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id="lab03admin",
    aws_secret_access_key="lab03-local-only",
    region_name="us-east-1",
    config=Config(s3={"addressing_style": "path"}),
)


def step(title):
    print(f"\n=== {title} ===")


step("1. Buckets that already exist")
for b in s3.list_buckets()["Buckets"]:
    print(" -", b["Name"])

step("2. Create bucket 'lab03'")
existing = [b["Name"] for b in s3.list_buckets()["Buckets"]]
if BUCKET in existing:
    print("already exists")
else:
    s3.create_bucket(Bucket=BUCKET)
    print("created")

step("3. PUT: upload two objects")
s3.put_object(
    Bucket=BUCKET,
    Key="students/ali/notes.txt",
    Body=b"Ali: GPA 3.5",
    ContentType="text/plain",
    Metadata={"student-id": "1"},
)
s3.put_object(Bucket=BUCKET, Key="students/sara/notes.txt", Body=b"Sara: GPA 3.8")
print("uploaded students/ali/notes.txt and students/sara/notes.txt")

step("4. LIST: objects whose key starts with 'students/'")
for obj in s3.list_objects_v2(Bucket=BUCKET, Prefix="students/").get("Contents", []):
    print(f" - {obj['Key']:<28} {obj['Size']:>4} bytes")

step("5. HEAD: metadata only, without downloading the data")
head = s3.head_object(Bucket=BUCKET, Key="students/ali/notes.txt")
print("size:", head["ContentLength"], "| type:", head["ContentType"], "| metadata:", head["Metadata"])

step("6. GET: download an object")
body = s3.get_object(Bucket=BUCKET, Key="students/ali/notes.txt")["Body"].read()
print("content:", body)

step("7. No partial update: to change an object, PUT the whole new version")
s3.put_object(Bucket=BUCKET, Key="students/ali/notes.txt", Body=b"Ali: GPA 3.9 (updated)")
print("content now:", s3.get_object(Bucket=BUCKET, Key="students/ali/notes.txt")["Body"].read())

step("8. Presigned URL: a temporary link that works without the keys")
url = s3.generate_presigned_url(
    "get_object", Params={"Bucket": BUCKET, "Key": "students/sara/notes.txt"}, ExpiresIn=60
)
print("link (valid 60 s):", url[:80] + "...")
print("opening it with plain HTTP:", urllib.request.urlopen(url).read())

step("9. DELETE an object")
s3.delete_object(Bucket=BUCKET, Key="students/sara/notes.txt")
left = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])]
print("objects left:", left)
