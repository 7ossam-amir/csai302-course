"""Shared Lab 1 connection helper for the course PostgreSQL service."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


COURSE_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(COURSE_ROOT / ".env")


def connect() -> psycopg.Connection:
    """Connect to the persistent local course database."""
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "csai302"),
        user=os.getenv("POSTGRES_USER", "csai302"),
        password=os.getenv("POSTGRES_PASSWORD", "csai302-local-only"),
    )
