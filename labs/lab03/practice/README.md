# Lab 3 Practice

An intermediate activity designed for about 60 minutes. Read [STUDENT_TASK.md](STUDENT_TASK.md) for the full instructions.

Students repeat the four parts of the lab on a different topic, a small library: shared-disk failover between `node1` and `node2`, a pointer table for book files, uploading and downloading the files through the object store, and checking the TLS connection. Everything uses the schema and bucket `practice03`, so the `lab03` data is not affected.

## Files

- `schema.sql`: the `practice03` tables to complete.
- `library.py`: five guided function stubs and a ready command line.
- `test_student.py`: checks for the tables, upload, listing, download, and TLS.
- `STUDENT_TASK.md`: requirements and submission instructions.

## Run

`node1` and `objectstore` must be running (see the [lab README](../README.md)).

```powershell
.\.venv\Scripts\python.exe labs\lab03\practice\test_student.py
```
