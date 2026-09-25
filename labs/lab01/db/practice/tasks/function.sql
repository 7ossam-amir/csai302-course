-- TODO: Return the total credits of the courses a student is enrolled in or has completed.
-- Withdrawn courses do not count. Return 0 when the student has no such courses.
CREATE OR REPLACE FUNCTION practice01.total_credits(p_student_id bigint)
RETURNS integer
LANGUAGE SQL
STABLE
AS $$
    SELECT 0;
$$;
