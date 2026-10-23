# Practice 6 — Build a selectivity-aware plan advisor

Extend the equality-only optimizer from the lab into an advisor for numeric range
filters and multiple predicates. The assignment is an independent implementation;
the public tests check the documented contract.

| File | Purpose |
|---|---|
| `STUDENT_TASK.md` | Scenario, API, mathematical contract, edge cases and marking |
| `student.py` | Your implementation stubs |
| `test_student.py` | Public tests; they fail predictably until the stubs are complete |

## Run (Windows PowerShell)

From the repository root, use the existing course environment:

```powershell
.\.venv\Scripts\python.exe labs\lab06\practice\test_student.py
```

The starter raises `NotImplementedError` by design. After implementation, the same
command should report all public tests passing. Do not change the tests to hide a
failure. The tests cover selectivity, path legality, and tie-breaking. No PostgreSQL
service is needed for this assignment.

## Submit

Submit your completed `student.py`, the test output, your own 2–3 additional tests,
and a short `results.md` with a table of at least four scenarios and your explanation
of each result. The results file is your work product; it is not included as a solved
starter example.
