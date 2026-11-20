# Lab 10 home practice

Implement the query language and the tenant-aware sharded store described in
`STUDENT_TASK.md`. The starter is in `student.py`; `test_student.py` contains the public
contract checks.

From the repository root, use the existing course environment:

```powershell
.\.venv\Scripts\python.exe labs\lab10\practice\test_student.py
```

The tests fail while the starter is unfinished. With the Lab 10 MongoDB instances running,
`check_against_mongo.py` compares your `match()` with MongoDB on 1,000 generated queries. Add
your own tests and results report as described in the assignment. Do not edit the public tests.
