-- Pointer pattern: the file bytes live in object storage, PostgreSQL keeps only metadata
-- and the object's address (bucket + object_key).
CREATE SCHEMA IF NOT EXISTS lab03;

-- Normally created in Part 1 (shared disk); repeated here so this part also works on its own.
CREATE TABLE IF NOT EXISTS lab03.students (
    id int PRIMARY KEY,
    name text,
    gpa numeric(3, 2),
    written_by text
);

CREATE TABLE IF NOT EXISTS lab03.documents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    student_id int NOT NULL REFERENCES lab03.students(id),
    file_name text NOT NULL,
    content_type text NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 char(64) NOT NULL,          -- fingerprint to verify the downloaded bytes
    bucket text NOT NULL,
    object_key text NOT NULL UNIQUE,
    uploaded_at timestamptz NOT NULL DEFAULT now()
);
