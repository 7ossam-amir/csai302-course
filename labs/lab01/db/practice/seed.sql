INSERT INTO practice01.departments (dept_code, dept_name) VALUES
    ('CS', 'Computer Science'), ('MATH', 'Mathematics'), ('PHYS', 'Physics')
ON CONFLICT (dept_code) DO NOTHING;

INSERT INTO practice01.students (full_name, email, dept_id)
SELECT v.full_name, v.email, d.id
FROM (VALUES
    ('Sara Ali',     'sara@example.edu',    'CS'),
    ('Omar Khaled',  'omar@example.edu',    'CS'),
    ('Nour Hany',    'nour@example.edu',    'MATH'),
    ('Youssef Adel', 'youssef@example.edu', 'PHYS'),
    ('Laila Samir',  'laila@example.edu',   'CS')
) AS v(full_name, email, dept_code)
JOIN practice01.departments d ON d.dept_code = v.dept_code
ON CONFLICT (email) DO NOTHING;

-- seats_available already accounts for the seeded enrollments below
INSERT INTO practice01.courses (course_code, title, credits, dept_id, seats_available)
SELECT v.course_code, v.title, v.credits, d.id, v.seats
FROM (VALUES
    ('CS101',   'Intro to Programming', 3, 'CS',   2),
    ('CS201',   'Databases',            3, 'CS',   1),
    ('MATH101', 'Calculus I',           4, 'MATH', 4),
    ('PHYS101', 'Mechanics',            4, 'PHYS', 3)
) AS v(course_code, title, credits, dept_code, seats)
JOIN practice01.departments d ON d.dept_code = v.dept_code
ON CONFLICT (course_code) DO NOTHING;

INSERT INTO practice01.enrollments (student_id, course_id, status, grade)
SELECT s.id, c.id, v.status, v.grade
FROM (VALUES
    ('sara@example.edu',    'CS101',   'completed', 88),
    ('sara@example.edu',    'CS201',   'enrolled',  NULL),
    ('omar@example.edu',    'CS101',   'completed', 72),
    ('omar@example.edu',    'CS201',   'enrolled',  NULL),
    ('nour@example.edu',    'MATH101', 'completed', 91),
    ('youssef@example.edu', 'PHYS101', 'enrolled',  NULL),
    ('laila@example.edu',   'CS101',   'withdrawn', NULL)
) AS v(email, course_code, status, grade)
JOIN practice01.students s ON s.email = v.email
JOIN practice01.courses c ON c.course_code = v.course_code
ON CONFLICT (student_id, course_id) DO NOTHING;
