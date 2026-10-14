-- Practice 3: a small library. Same pointer pattern as large_objects/schema.sql:
-- the file bytes live in object storage, PostgreSQL keeps only metadata and the address.
CREATE SCHEMA IF NOT EXISTS practice03;

-- TODO: practice03.books
--   id int primary key, title text not null, author text not null,
--   written_by text   (which node inserted the row: 'node1' or 'node2')


-- TODO: practice03.book_files
--   id: generated identity primary key
--   book_id: not null, references practice03.books(id)
--   file_name, content_type: text not null
--   size_bytes: bigint not null
--   sha256: char(64) not null
--   bucket: text not null
--   object_key: text not null and unique
--   uploaded_at: timestamptz not null, default now()
-- Use CREATE TABLE IF NOT EXISTS so the file can be run again.
