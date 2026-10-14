# Lab 3 Practice — A Small Library

Difficulty: intermediate. Suggested time: 60 minutes.

Repeat the four parts of the lab on a different topic. Instead of students and their documents, you build a small **library**: books in PostgreSQL, and the books' files (covers, PDFs, notes) in object storage. Everything lives in the schema `practice03` and the bucket `practice03`, so it does not affect the `lab03` data.

Use the same services as the lab (`node1`, `node2`, `objectstore`) and the same certificates. Each step below names the lab file to copy the idea from.

## Before you start

- Docker Desktop is running, and you ran `tls/make_certs.py` during the lab.
- `node1` and `objectstore` are running. **Only one of `node1` / `node2` may run at a time.**

## Part 1 — Shared disk: two nodes, one library

Like Part 1 of the lab, but with books.

1. On `node1`, create the schema and the books table, and add three books with `written_by = 'node1'`:

   ```powershell
   docker exec csai302-lab03-node1-1 psql -U csai302 -d csai302 -c "CREATE SCHEMA IF NOT EXISTS practice03; CREATE TABLE IF NOT EXISTS practice03.books (id int PRIMARY KEY, title text NOT NULL, author text NOT NULL, written_by text);"
   ```

   Write the `INSERT` for the three books yourself.
2. Stop `node1`, start `node2`, and show that `node2` sees the three books.
3. From `node2`, add a fourth book with `written_by = 'node2'`.
4. Stop `node2`, start `node1` again, and show that `node1` sees all four books.

Leave `node1` running for the next parts.

## Part 2 — Database schema for the files (`schema.sql`)

Complete `schema.sql`. It must create both tables (`books` and `book_files`) with `CREATE TABLE IF NOT EXISTS`. The column list is in the comments. Copy the idea from `large_objects/schema.sql`: `book_files` stores the file's metadata and its address (`bucket` + `object_key`), never the bytes.

## Part 3 — Files in object storage (`library.py`)

Complete the five functions in `library.py`. The command-line part at the bottom is already written.

| Function | Copy the idea from | What it does |
|---|---|---|
| `setup()` | `large_objects/setup.py` | runs `schema.sql`, creates the bucket `practice03` if missing |
| `upload_file(book_id, path)` | `large_objects/upload.py` | key `books/<book_id>/<uuid>-<name>`, `put_object`, then `INSERT`; if the `INSERT` fails, delete the object and re-raise |
| `list_files(book_id)` | `list_documents()` in `download.py` | returns `[(file_id, file_name, size_bytes), ...]` ordered by id |
| `download_file(file_id)` | `download()` in `download.py` | looks up the row, fetches the object, checks the SHA-256, saves into `practice/downloads/`; returns the path, or `None` for an unknown id; raises `ValueError` if the fingerprint does not match |
| `tls_info()` | `tls/check_tls.py` | returns `{'ssl': ..., 'version': ..., 'cipher': ...}` |

Then run, from the repository root:

```powershell
python labs/lab03/practice/library.py setup
python labs/lab03/practice/library.py upload 1 <a file of your choice>
python labs/lab03/practice/library.py upload 2 <another file>
python labs/lab03/practice/library.py list 1
python labs/lab03/practice/library.py download <the file id printed by upload>
python labs/lab03/practice/library.py upload 99 <any file>
```

The last command uses a book that does not exist. It must fail, and no object may be left under `books/99/`. Check this in the web console (<http://localhost:9001/rustfs/console/>, bucket `practice03`).

## Part 4 — TLS

1. Run `python labs/lab03/practice/library.py tls` and record the TLS version and cipher.
2. Run `python labs/lab03/tls/check_tls.py` again. For each of the five tests, write one line explaining why it was accepted or refused.

## Check your work

```powershell
.\.venv\Scripts\python.exe labs\lab03\practice\test_student.py
```

The checks use only book 9001, which they create and delete themselves, so your own books and files are not touched. `library.py` raises `NotImplementedError` until completed.

## What to Submit

- `schema.sql` and `library.py`, completed.
- `results.md` with:
  - the commands and output of Part 1 (from both nodes),
  - the output of the Part 3 commands, including the failed upload, and a screenshot of the bucket in the web console,
  - the output of Part 4 and your five explanations,
  - the output of `test_student.py`,
  - short answers:
    1. In Part 1, why must `node1` be stopped before `node2` starts?
    2. Why does `book_files` store `object_key` instead of the file itself (`BYTEA`)?
    3. Why does the key contain a uuid?
    4. What is the difference between `sslmode=require` and `sslmode=verify-full`?

Do not modify the provided checks or the original lab files. Do not submit certificates, keys, the `downloads/` folder or your virtual environment.
