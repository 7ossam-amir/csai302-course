"""Connections shared by the large-object scripts: PostgreSQL (lab03 node1) and object storage."""
import os
from pathlib import Path

import boto3
import psycopg
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

BUCKET = "lab03"
CA_CERT = Path(__file__).resolve().parents[1] / "tls" / "certs" / "ca.crt"


def connect_db():
    return psycopg.connect(
        host="localhost",
        port=os.getenv("LAB03_PG_PORT", "5434"),  # node1; use 5435 when node2 is the running node
        dbname=os.getenv("POSTGRES_DB", "csai302"),
        user=os.getenv("POSTGRES_USER", "csai302"),
        password=os.getenv("POSTGRES_PASSWORD", "csai302-local-only"),
        sslmode="verify-full",  # the nodes only accept TLS; also check the server's certificate
        sslrootcert=str(CA_CERT),
    )


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id=os.getenv("S3_ACCESS_KEY", "lab03admin"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY", "lab03-local-only"),
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
