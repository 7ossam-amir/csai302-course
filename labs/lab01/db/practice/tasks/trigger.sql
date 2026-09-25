-- TODO: Reserve one seat in the course when a new enrollment is inserted.
-- Test a course with a free seat and a course that is full.
CREATE OR REPLACE FUNCTION practice01.reserve_course_seat()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- NEW contains the row being inserted into enrollments.
    -- Add the seat behavior, then decide what should happen when the course is full.
    RETURN NEW;
END;
$$;

-- TODO: Create a trigger that calls practice01.reserve_course_seat().
