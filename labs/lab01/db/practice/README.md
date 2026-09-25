# Practice 1 — Course registration database

Apply what you did in the live lab to a different domain. You will write a function, a procedure and a trigger, and then repair an injectable Python query. Everything lives in the schema `practice01` of the course database, so it does not affect the `lab01` order system.

Run all Docker commands from the repository root. Commands below are for Windows Command Prompt; in PowerShell replace `type file.sql |` with `Get-Content file.sql |`.

## Load the database

    type labs\lab01\db\practice\schema.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    type labs\lab01\db\practice\seed.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

Check it:

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "\dt practice01.*"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT s.full_name, c.course_code, e.status, e.grade FROM practice01.enrollments e JOIN practice01.students s ON s.id = e.student_id JOIN practice01.courses c ON c.id = e.course_id ORDER BY e.id;"

You should see four tables and seven enrollments.

## The data

| Table | Important columns and rules |
| --- | --- |
| `departments` | `dept_code` (unique), `dept_name` |
| `students` | `full_name`, `email` (unique), `dept_id` |
| `courses` | `course_code` (unique), `title`, `credits` (> 0), `seats_available` (>= 0) |
| `enrollments` | `student_id`, `course_id`, `status` in (enrolled, completed, withdrawn), `grade` 0-100; one row per student and course |

`seats_available` in the seed already accounts for the seeded enrollments.

Each task file is in `labs/lab01/db/practice/tasks/`. Edit the file, then load it again with the command shown, because editing a file does not change the database.

## Task 1 — Function `practice01.total_credits(p_student_id)`

File: `tasks/function.sql`

Return the total credits of the courses a student is **enrolled in or has completed**. Withdrawn courses do not count. A student with no such courses gets **0**, not `NULL`. Keep `LANGUAGE SQL` and `STABLE`.

    type labs\lab01\db\practice\tasks\function.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT s.full_name, practice01.total_credits(s.id) FROM practice01.students s ORDER BY s.full_name;"

Expected: Laila Samir 0, Nour Hany 4, Omar Khaled 6, Sara Ali 6, Youssef Adel 4.

Hints: join `enrollments` to `courses`; filter on the student and on status; `SUM` over no rows is `NULL`.

## Task 2 — Procedure `practice01.update_enrollment_status(p_enrollment_id, p_new_status)`

File: `tasks/procedure.sql`

Change the status of one enrollment. If the enrollment does not exist, raise an exception with a clear message. Do not list the allowed statuses in your code; observe what the `CHECK` constraint does with an invalid one.

    type labs\lab01\db\practice\tasks\procedure.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

Look up an enrollment id first, then use that id (a procedure call needs a literal id):

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT e.id, s.full_name, c.course_code, e.status FROM practice01.enrollments e JOIN practice01.students s ON s.id = e.student_id JOIN practice01.courses c ON c.id = e.course_id ORDER BY e.id;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL practice01.update_enrollment_status(1, 'completed');"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL practice01.update_enrollment_status(1, 'dropped');"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "CALL practice01.update_enrollment_status(9999, 'completed');"

Expected: the first call prints `CALL`; the second fails with a check-constraint error; the third fails with your own message. A procedure returns no rows, so run the `SELECT` again to see the change.

Hint: after an `UPDATE`, the PL/pgSQL variable `FOUND` tells you whether a row was changed.

## Task 3 — Trigger: reserve a seat

File: `tasks/trigger.sql`

When a row is inserted into `practice01.enrollments`, reduce `seats_available` of that course by one. If the course has no free seat, reject the insert with an error. Complete `practice01.reserve_course_seat()` and create a **BEFORE INSERT, FOR EACH ROW** trigger on `enrollments`. Use `DROP TRIGGER IF EXISTS` first so the file can be re-run.

    type labs\lab01\db\practice\tasks\trigger.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302

CS201 has one free seat. Check the seats, enroll Laila (should succeed), then enroll Nour (should fail because the course is full):

    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT course_code, seats_available FROM practice01.courses ORDER BY course_code;"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "INSERT INTO practice01.enrollments (student_id, course_id) SELECT s.id, c.id FROM practice01.students s, practice01.courses c WHERE s.email = 'laila@example.edu' AND c.course_code = 'CS201';"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "INSERT INTO practice01.enrollments (student_id, course_id) SELECT s.id, c.id FROM practice01.students s, practice01.courses c WHERE s.email = 'nour@example.edu' AND c.course_code = 'CS201';"
    docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U csai302 -d csai302 -c "SELECT course_code, seats_available FROM practice01.courses ORDER BY course_code;"

Expected: the first insert succeeds and CS201 drops to 0 seats; the second fails with your error and adds no row.

Explain in your own words: what does `NEW` contain here? What happens to the insert when the trigger raises an error? What could go wrong if two students take the last seat at the same moment?

## Task 4 — SQL injection

Files: `labs/lab01/python/practice/vulnerable_query.py` and `parameterized_query_starter.py`

Python connects through `POSTGRES_PORT` in `.env`. Run from `labs\lab01\python` with `.venv` active. Use `python -m` so that the shared `db.py` can be imported:

    .venv\Scripts\activate.bat
    cd labs\lab01\python
    python -m practice.vulnerable_query

Type each of these at the `Student name:` prompt (start the program again for each one):

    Sara Ali
    ' OR '1'='1
    x' UNION SELECT email, full_name FROM practice01.students --

1. Write down what each input returned and why. Which one leaks data from another table?
2. Repair `parameterized_query_starter.py`: keep the SQL text fixed, use a placeholder for the value, and pass the value separately as a parameter.
3. Run it with the same three inputs:

       python -m practice.parameterized_query_starter

Expected after the repair: `Sara Ali` still returns her enrollments; the other two inputs return `[]`.

Discussion: why can a placeholder not be used for a table or column name?

## Reset practice data

Only when you want to start over. This drops the schema `practice01`, including your function, procedure and trigger, so load the schema, the seed and your task files again afterwards.

    type labs\lab01\db\practice\reset.sql | docker compose --env-file .env -f infra/compose.yaml exec -T postgres psql -U csai302 -d csai302
