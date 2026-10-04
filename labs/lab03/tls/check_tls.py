"""Try connecting to the lab03 PostgreSQL node with different TLS settings.

Run: python labs/lab03/tls/check_tls.py
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
CERTS = Path(__file__).parent / "certs"

BASE = dict(
    host="localhost",
    port=os.getenv("LAB03_PG_PORT", "5434"),
    dbname=os.getenv("POSTGRES_DB", "csai302"),
    user=os.getenv("POSTGRES_USER", "csai302"),
    password=os.getenv("POSTGRES_PASSWORD", "csai302-local-only"),
    connect_timeout=5,
)

TESTS = [
    ("1. no TLS (sslmode=disable)", dict(sslmode="disable")),
    ("2. TLS, server not verified (sslmode=require)", dict(sslmode="require")),
    ("3. TLS + our CA + host name (sslmode=verify-full)",
     dict(sslmode="verify-full", sslrootcert=str(CERTS / "ca.crt"))),
    ("4. verify-full, but trusting a different CA",
     dict(sslmode="verify-full", sslrootcert=str(CERTS / "wrong-ca.crt"))),
    ("5. verify-full, but a host name not in the certificate",
     dict(sslmode="verify-full", sslrootcert=str(CERTS / "ca.crt"), host="db.example.com",
          hostaddr="127.0.0.1")),
]

for title, options in TESTS:
    print(f"\n=== {title} ===")
    try:
        with psycopg.connect(**{**BASE, **options}) as conn:
            ssl, version, cipher = conn.execute(
                "SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
            ).fetchone()
            print(f"CONNECTED  ssl={ssl}  version={version}  cipher={cipher}")
    except psycopg.OperationalError as e:
        print("REFUSED   ", str(e).strip().splitlines()[-1])
