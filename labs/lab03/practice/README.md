# Lab 3 Practice

An easy-to-intermediate activity designed for 45–60 minutes. Read [STUDENT_TASK.md](STUDENT_TASK.md) for the full instructions.

Students use the existing object store and TLS connection to list one student's objects, detect rows and objects that no longer match, delete a document from both systems in a safe order, and inspect the TLS session. No change to the lab scripts, certificates or Docker services is required.

## Files

- `student.py`: four guided function stubs.
- `test_student.py`: checks for prefix listing, inconsistency detection, document deletion, and TLS details.
- `STUDENT_TASK.md`: requirements and submission instructions.

Submit the completed functions, an experiment script, and your own measured results.

## Run

`node1` and `objectstore` must be running (see the [lab README](../README.md)).

```powershell
.\.venv\Scripts\python.exe labs\lab03\practice\test_student.py
```
