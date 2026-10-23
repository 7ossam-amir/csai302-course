# Lab 5 — ORM, Safe Queries, and Query Execution

This lab connects two sides of database work. First, you’ll use a small Python
application to read and write customer orders safely. Then you’ll build simple query
operators and compare processing one row at a time with processing batches of rows.
The final example uses a hash join to show where vectorized CPU operations can help.

You can run the main exercises with Python and SQLite; PostgreSQL is optional. The
native C++ SSE2 example is an extension for comparing an explicit SIMD implementation
with the Python versions.

## Start here

Run these commands from the repository root with the course `.venv` active:

```powershell
python -m pip install -r labs\lab05\requirements.txt
python labs\lab05\orm_demo.py
python labs\lab05\test_lab05.py
python labs\lab05\bench_executor.py
```

The first run installs SQLAlchemy and NumPy in the course environment. The demo uses
an in-memory SQLite database by default, so it does not require Docker or a running
PostgreSQL server.

To try the same ORM example with the course PostgreSQL database, start that database
first, check that the repository-root `.env` has the correct connection settings, and
run:

```powershell
python labs\lab05\orm_demo.py --postgres
```

The PostgreSQL run creates only `lab05_customers` and `lab05_orders`; it does not
drop or modify tables from other labs. Sample rows are inserted only when the customer
table is empty. The default SQLite run and the tests use temporary in-memory data.

## Part 1 — Use the ORM and keep queries safe

Start with `orm_demo.py`. The `Customer` and `Order` Python classes describe two
database tables, including the foreign key from each order to its customer. SQLAlchemy
uses those mappings to build and run queries. The `seed()` function creates the two
tables if needed and adds a few sample customers and orders when the customer table is
empty.

The demo then sends requests through `QueryService`:

- A `viewer` can look up a customer.
- An `analyst` can also run a report for orders above a minimum amount.
- An `admin` can read, report, and add orders.
- Unknown roles are denied.

For the sample data, the lookup finds Mona, the injection-shaped input finds nobody,
and a report with a minimum of 200 includes Ali's 250 order and Mona's 400 order. A
viewer who tries to run that report gets a `PermissionError`.

Try the lookup for Mona, then notice what happens when the input is the string
`' OR 1=1 --`. The value is passed as data, so it does not change the meaning of the
query and returns no customers. In the ORM expression `Customer.name == name`,
SQLAlchemy binds `name` as a value. The report demonstrates the same idea with the
bound parameter `:minimum`. Do not build SQL by inserting user values into a string.

Parameter binding is for values, not table or column names. If a program needs to
choose a column dynamically, it must select from an explicit allowlist. Also, the
roles here are an application-level teaching example: this demo has no login system
or PostgreSQL roles. A real application must get the user's role from trusted
authentication and prevent untrusted code from bypassing `QueryService` through direct
access to the session.

When `add_order()` is called, the service checks the role and rejects negative
amounts. It adds the order to the SQLAlchemy session and calls `flush()`; the caller
still controls whether the transaction is committed or rolled back. The tests use a
rollback to show that an inserted order can be undone before commit.

## Part 2 — Follow a query through its operators

In `executors.py`, the Volcano-style pipeline processes one row at a time:

```text
Scan rows → Filter matching rows → Project selected columns → Results
```

The caller asks `Project` for a row. It asks `Filter`, which keeps pulling from
`Scan` until a row passes the condition or the input ends. `None` means there are no
more rows. Each operator has `open()`, `next()`, and `close()` methods. The `collect()`
helper opens the pipeline, gathers its rows, and closes it even if an error occurs.
Calling it again reopens the scan.

The vectorized pipeline follows the same idea but works on column arrays in batches:

```text
Column arrays → VectorScan batch → Boolean mask → VectorProject → Results
```

`VectorFilter` creates one Boolean value per row and applies that mask to every
column in the batch. It skips batches with no matching rows. The final batch can be
smaller than the requested batch size. `collect_batches()` converts the batches back
to row dictionaries so the tests and benchmark can compare them with the row-at-a-time
result.

## Part 3 — Compare hash joins

The scalar join builds a dictionary from each key on the left to its row positions,
then probes that dictionary for every key on the right. The NumPy version groups left
keys into hash buckets and compares each right key against the keys in its bucket.
Hashing narrows the candidates; the equality check handles collisions. Every matching
pair is returned, including duplicate-key combinations, as an inner join should.

NumPy may use SIMD-capable CPU kernels for array comparisons, depending on the NumPy
build and processor. The Python code still performs hashing, probing, and result
construction in Python, so it is not guaranteed to be faster. `np.show_runtime()` can
show available CPU capabilities, but it does not prove that a particular comparison
used a particular instruction.

The optional `simd_hash_join.cpp` version makes the SIMD step explicit with SSE2: it
compares four signed 32-bit keys at a time, then checks any remaining keys one by one.
It verifies its output against a simple nested-loop join on empty inputs, duplicates,
negative keys, collisions, and random test data. Compiling it requires a separate
x64 C++ toolchain; it is not installed by the Python requirements.

With GCC or MinGW, compile and run it from the repository root:

```powershell
g++ -O2 -std=c++17 -msse2 labs\lab05\simd_hash_join.cpp -o labs\lab05\simd_hash_join.exe
.\labs\lab05\simd_hash_join.exe
```

Or use a Visual Studio x64 Developer PowerShell:

```powershell
cl /O2 /EHsc /std:c++17 labs\lab05\simd_hash_join.cpp /Fe:labs\lab05\simd_hash_join.exe
.\labs\lab05\simd_hash_join.exe
```

## Check your results

`test_lab05.py` compares the joins with an independent nested-loop result and checks
edge cases such as empty inputs, duplicate keys, collisions, and negative keys. It
also checks batch boundaries, reopening an operator, parameter binding, role checks,
and transaction rollback. Run it with:

```powershell
python labs\lab05\test_lab05.py
```

`bench_executor.py` first confirms that the row and vectorized pipelines return the
same results, then prints local timings. It also compares the scalar and NumPy joins
before showing timing results and NumPy's available runtime capabilities. Your timing
will depend on the machine, Python, and NumPy build; one run is an observation, not a
performance guarantee. In particular, vectorization can be slower on small inputs or
when Python overhead dominates.

## Questions to consider

- Where is the user-provided customer name bound in the ORM lookup?
- Why is `:minimum` safer than formatting the report SQL with a string?
- Which operator requests each row in the Volcano pipeline, and what ends the scan?
- How does a Boolean mask apply the same filter to every column in a batch?
- Why does the hash join still compare actual keys after choosing a bucket?
- What does the benchmark verify before it reports a time, and what does it not prove?


