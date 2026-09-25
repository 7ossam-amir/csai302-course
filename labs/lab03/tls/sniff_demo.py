"""See TLS with your own eyes: eavesdrop on the network while Python talks to PostgreSQL.

Run: python labs/lab03/tls/sniff_demo.py      (node1 must be running)

It sends the same query twice and records the network traffic with tcpdump:
  1. to a throwaway PostgreSQL WITHOUT TLS (started on port 5436, removed at the end)
  2. to node1, which uses TLS
"""
import os
import re
import subprocess
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
USER = os.getenv("POSTGRES_USER", "csai302")
PASSWORD = os.getenv("POSTGRES_PASSWORD", "csai302-local-only")
DB = os.getenv("POSTGRES_DB", "csai302")
CA = Path(__file__).parent / "certs" / "ca.crt"

PLAIN = "csai302-lab03-plain"
SNIFFER = "csai302-lab03-sniffer"
SNIFFER_IMAGE = "csai302-lab03-tcpdump"
QUERY = "SELECT 'Walaa' AS student, 'GPA 4.00' AS gpa, 'SECRET-MESSAGE' AS note"
WORDS = ["SELECT", "Walaa", "GPA 4.00", "SECRET-MESSAGE", USER]


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def prepare():
    if docker("image", "inspect", SNIFFER_IMAGE, check=False).returncode:
        subprocess.run(["docker", "build", "-q", "-t", SNIFFER_IMAGE, "-"], check=True, text=True,
                       input="FROM alpine:3.20\nRUN apk add --no-cache tcpdump\n")
    docker("rm", "-f", PLAIN, check=False)
    docker("run", "-d", "--name", PLAIN, "-p", "5436:5432", "-e", f"POSTGRES_USER={USER}",
           "-e", f"POSTGRES_PASSWORD={PASSWORD}", "-e", f"POSTGRES_DB={DB}", "postgres:17.11")
    for _ in range(60):  # wait until the plain server accepts network connections
        try:
            psycopg.connect(host="localhost", port=5436, dbname=DB, user=USER, password=PASSWORD,
                            sslmode="disable", connect_timeout=2).close()
            return
        except psycopg.OperationalError:
            time.sleep(1)
    raise RuntimeError("the plain PostgreSQL server did not start")


def sniff(container, port, **tls):
    """Record the traffic of one connection + query, as seen by an eavesdropper."""
    docker("rm", "-f", SNIFFER, check=False)
    docker("run", "-d", "--name", SNIFFER, "--net", f"container:{container}", SNIFFER_IMAGE,
           "tcpdump", "-i", "any", "-A", "-s0", "-U", "port", "5432")
    for _ in range(60):  # tcpdump prints "listening on ..." once it is recording
        if "listening on" in docker("logs", SNIFFER).stderr:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError("tcpdump did not start")
    time.sleep(1)
    with psycopg.connect(host="localhost", port=port, dbname=DB, user=USER, password=PASSWORD,
                         **tls) as conn:
        conn.execute(QUERY).fetchone()
    for _ in range(20):  # give tcpdump time to write the captured packets
        time.sleep(0.5)
        output = docker("logs", SNIFFER).stdout
        if "ReadyForQuery" in output or len(output) > 1000:
            break
    time.sleep(1)
    output = docker("logs", SNIFFER).stdout
    docker("rm", "-f", SNIFFER)
    lines = [ln for ln in output.splitlines() if not re.match(r"^\d\d:\d\d:\d\d", ln)]
    return re.sub(r"\.{3,}", " ... ", "".join(lines))  # squeeze runs of unreadable bytes


def report(title, traffic):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(f"captured {len(traffic):,} characters of network traffic\n")
    print("What a spy on the network can read:")
    for word in WORDS:
        i = traffic.find(word)
        if i >= 0:
            print(f"  FOUND     {word!r:<20} ...{traffic[max(0, i - 25):i + len(word) + 25]}...")
        else:
            print(f"  not found {word!r}")
    sample = traffic[len(traffic) // 2:len(traffic) // 2 + 120]
    print(f"\nA piece of the raw traffic:\n  {sample}")


if __name__ == "__main__":
    print("preparing (a throwaway PostgreSQL without TLS on port 5436) ...")
    prepare()
    try:
        report("1. WITHOUT TLS  (sslmode=disable, throwaway server)",
               sniff(PLAIN, 5436, sslmode="disable"))
        report("2. WITH TLS  (sslmode=verify-full, node1)",
               sniff("csai302-lab03-node1-1", 5434, sslmode="verify-full", sslrootcert=str(CA)))
    finally:
        docker("rm", "-f", PLAIN, SNIFFER, check=False)
