-- TODO: Update the requested enrollment's status.
-- If the enrollment does not exist, raise an exception with a clear message.
-- Consider how the CHECK constraint on enrollments.status handles an invalid value.
CREATE OR REPLACE PROCEDURE practice01.update_enrollment_status(
    p_enrollment_id bigint,
    p_new_status text
)
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE NOTICE 'Implement the status update for enrollment %', p_enrollment_id;
END;
$$;
