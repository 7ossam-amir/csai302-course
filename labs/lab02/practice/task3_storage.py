"""Task 3 - queries on the row store and the column store, and the reverse conversion.

The table is the lab's students table: (id int, name char(20), gpa float).
`rows` is a RowStore (../row_store.py), `cols` is a ColumnStore (../column_store.py).

Check: python check.py 3
"""
import common  # noqa: F401  (makes the lab code importable)


def count_honors_row(rows, min_gpa):
    """Number of students with gpa >= min_gpa, using the ROW store."""
    # TODO: use rows.scan()
    raise NotImplementedError("Task 3: count_honors_row")


def count_honors_column(cols, min_gpa):
    """The same number, using the COLUMN store. Read only the column you need."""
    # TODO: use cols.scan_column(...)
    raise NotImplementedError("Task 3: count_honors_column")


def honor_names_column(cols, min_gpa):
    """List of the names of students with gpa >= min_gpa, in table order (COLUMN store).

    Read only the two columns the query needs; do not read the id column.
    """
    # TODO: values at the same position in two columns belong to the same row.
    raise NotImplementedError("Task 3: honor_names_column")


def convert_column_to_row(cols, rows):
    """The reverse of the lab's convert_row_to_column: fill the empty row store from the column store."""
    # TODO: rebuild each row (id, name, gpa) from the three columns and call rows.insert(row).
    raise NotImplementedError("Task 3: convert_column_to_row")
