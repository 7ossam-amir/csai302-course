# Lab 3 — Shared Disk, Object Storage, and TLS

| Task | How this lab does it |
|---|---|
| Emulate a shared-disk architecture using local storage | Two PostgreSQL servers (`node1`, `node2`) attached to **one** Docker volume |
| Simulate object storage using S3-like APIs | A local S3-compatible object store + `boto3` |
| Configure a database to use external object storage for large data | PostgreSQL keeps file metadata and the object's address; the bytes live in the object store |
| Enable TLS for DB communication | Our own CA + server certificate, `ssl=on`, `pg_hba.conf` rejects unencrypted connections |

> **Why RustFS instead of MinIO?** MinIO no longer publishes free Docker images
> (`docker pull minio/minio` fails). [RustFS](https://github.com/rustfs/rustfs) is an
> S3-compatible replacement with the same ports (9000 API, 9001 web console). The Python code
> uses the standard S3 API, so it would work unchanged against MinIO or Amazon S3.

## Files

| File | Purpose |
|---|---|
| `compose.lab03.yaml` | Services for this lab: `node1` (port 5434), `node2` (port 5435), `objectstore` (9000/9001) |
| `object_storage/s3_basics.py` | The basic S3 API calls: buckets, put, list, head, get, overwrite, presigned URL, delete |
| `large_objects/schema.sql` | `lab03.students` and `lab03.documents` (file metadata + `bucket` / `object_key`) |
| `large_objects/common.py` | Shared connections to PostgreSQL (over TLS) and to the object store |
| `large_objects/setup.py` | Creates the tables and the `lab03` bucket |
| `large_objects/upload.py` | Uploads a file to the object store, then inserts its pointer row |
| `large_objects/download.py` | Lists documents, or looks one up in PostgreSQL and fetches it from the object store |
| `tls/make_certs.py` | Creates a local CA, the server certificate/key, and an unrelated CA for testing |
| `tls/pg_hba.conf` | Client rules: TLS + password over the network, everything else rejected |
| `tls/check_tls.py` | Connects with different `sslmode` settings and shows which are accepted |
| `tls/sniff_demo.py` | Records the network traffic with and without TLS to show what an eavesdropper sees |

This lab's services and volumes (`csai302-lab03-*`) are separate from the course database on
port 5433; nothing here touches the Lab 1 data.

## Setup (once)

All commands run from the **repository root** (`csai302-course`), with Docker Desktop running and
the course `.venv` activated.

```powershell
pip install -r requirements.txt
python labs/lab03/tls/make_certs.py
```

The certificates are needed before the database nodes start, because the nodes run with TLS on.
They are written to `labs/lab03/tls/certs/`, which is git-ignored: `*.key` files are secrets, so
everyone generates their own.

## Part 1 — Shared disk (failover)

`node1` and `node2` are two PostgreSQL servers mounting the same volume
`csai302-lab03-shared-data`. PostgreSQL does not coordinate two servers writing the same files,
so **only one node may run at a time**: stop one before starting the other. (This is also why
both nodes use `restart: "no"`.)

Start `node1` and create some data:

```powershell
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml up -d --wait node1
docker exec csai302-lab03-node1-1 psql -U csai302 -d csai302 -c "CREATE SCHEMA IF NOT EXISTS lab03; CREATE TABLE IF NOT EXISTS lab03.students (id int PRIMARY KEY, name text, gpa numeric(3,2), written_by text); INSERT INTO lab03.students VALUES (1,'Ali',3.50,'node1'), (2,'Sara',3.80,'node1'), (3,'Omar',3.20,'node1') ON CONFLICT DO NOTHING;"
```

"Crash" `node1` and let `node2` take over the same disk:

```powershell
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml stop node1
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml up -d --wait node2
docker exec csai302-lab03-node2-1 psql -U csai302 -d csai302 -c "SELECT * FROM lab03.students ORDER BY id;"
docker exec csai302-lab03-node2-1 psql -U csai302 -d csai302 -c "INSERT INTO lab03.students VALUES (4,'Mona',3.90,'node2') ON CONFLICT DO NOTHING;"
```

`node2` sees the rows written by `node1` without any copy. Switch back and `node1` sees Mona:

```powershell
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml stop node2
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml up -d --wait node1
docker exec csai302-lab03-node1-1 psql -U csai302 -d csai302 -c "SELECT * FROM lab03.students ORDER BY id;"
```

Real shared-disk databases (e.g. Oracle RAC) let several nodes run at once, but need a cluster
lock manager and cache invalidation between the nodes' buffer pools; PostgreSQL has neither.

**Leave `node1` running** for the next parts.

## Part 2 — S3-like object storage

```powershell
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml up -d objectstore
python labs/lab03/object_storage/s3_basics.py
```

Web console: <http://localhost:9001/rustfs/console/> — account `lab03admin`, key
`lab03-local-only` (local lab credentials only). The console and the script operate on the same
buckets; the console is for people, the S3 API is for programs.

Things to notice in the output:

- **Keys are flat names.** `students/ali/notes.txt` is one key; the "folders" are only a prefix.
- **No partial updates.** Changing an object means uploading a whole new version under the same key.
- **Presigned URL.** A temporary link that works without credentials and expires.

## Part 3 — Large data in object storage, metadata in PostgreSQL

```powershell
python labs/lab03/large_objects/setup.py
python labs/lab03/large_objects/upload.py 1 labs/lab02/buffer_hit_ratio.png
python labs/lab03/large_objects/download.py
python labs/lab03/large_objects/download.py 1
```

`upload.py <student_id> <file>`:

1. computes a SHA-256 fingerprint of the file,
2. `put_object` stores the bytes at `students/<id>/<uuid>-<name>` (the uuid avoids overwriting),
3. `INSERT` stores the metadata and the address in `lab03.documents`.

If the `INSERT` fails (for example an unknown student id), the object is deleted again, so no
orphan object is left in storage:

```powershell
python labs/lab03/large_objects/upload.py 99 labs/lab02/buffer_hit_ratio.png
```

`download.py <document_id>` asks PostgreSQL where the file is, fetches the bytes from the object
store, checks the fingerprint, and saves the file in `large_objects/downloads/`.

Why not store the file inside PostgreSQL (`BYTEA`)? Large files make the database, its backups and
its buffer pool much bigger, and every `SELECT *` moves the file bytes. Keeping only a pointer
keeps the database small; the cost is that two systems must be kept consistent.

## Part 4 — TLS for database connections

What the lab changes:

- `tls/make_certs.py` creates a **CA** (a local authority we trust) and a **server certificate**
  for `localhost` / `127.0.0.1`, signed by that CA.
- `compose.lab03.yaml` starts both nodes with `ssl=on`, the certificate and key, TLS 1.2 minimum,
  and `tls/pg_hba.conf`. PostgreSQL refuses to start if its private key is readable by others, and
  files mounted from Windows appear world-readable, so the nodes first copy them with mode `600`.
- `tls/pg_hba.conf` accepts network connections only as `hostssl` (with a password) and rejects
  `hostnossl`.
- `large_objects/common.py` connects with `sslmode=verify-full` and the CA certificate.

```powershell
python labs/lab03/tls/check_tls.py
```

| Test | Result | Reason |
|---|---|---|
| `sslmode=disable` | refused | `pg_hba.conf` rejects connections with no encryption |
| `sslmode=require` | connected | encrypted, but the server's identity is not checked |
| `sslmode=verify-full` + our CA | connected | encrypted, certificate signed by our CA, host name matches |
| `verify-full` + a different CA | refused | `certificate verify failed` |
| `verify-full` + host `db.example.com` | refused | the certificate is for `localhost`, not that name |

Connected sessions report `ssl=True`, `TLSv1.3`, cipher `TLS_AES_256_GCM_SHA384`. Only
`verify-full` protects against a server pretending to be the database: `require` encrypts, but
would happily send the password to an impostor.

To **see** the difference, eavesdrop on the network with `tcpdump` while the same query is sent to
a throwaway server without TLS and to `node1` with TLS (the throwaway server is removed at the end):

```powershell
python labs/lab03/tls/sniff_demo.py
```

Without TLS, the user name, database, the SQL text and the result values are readable in the
captured traffic. With TLS, none of them can be found; the traffic is unreadable bytes. (The
password itself is not visible in either case, because PostgreSQL's `scram-sha-256` never sends it
directly — but everything else is.)

Inside the database you can check your own connection with:

```sql
SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid();
```

### SQLTools (optional)

To browse the lab03 nodes in VS Code, add PostgreSQL connections on ports `5434` (node1) and
`5435` (node2) with the course user and password, and enable SSL with the CA file
`labs/lab03/tls/certs/ca.crt` (in `settings.json`:
`"pgOptions": {"ssl": {"rejectUnauthorized": true, "ca": "<full path to ca.crt>"}}`). Only the node
that is currently running will connect.

## Stop and reset

Stop the lab services (data is kept):

```powershell
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml stop
```

Delete this lab's containers **and its data** (only the `csai302-lab03-*` volumes; the course
database is not affected):

```powershell
docker compose --env-file .env -f labs/lab03/compose.lab03.yaml down -v
```
