"""Column-oriented storage (DSM): each column is stored in its own list of pages."""
import struct

from disk_manager import PAGE_SIZE
from row_store import HEADER

COLUMNS = {"id": struct.Struct("<i"), "name": struct.Struct("<20s"), "gpa": struct.Struct("<f")}


class ColumnStore:
    def __init__(self, bpm):
        self.bpm = bpm
        self.next_page = 0
        self.pages = {c: [] for c in COLUMNS}  # column -> its page ids
        self.num_rows = 0

    def _per_page(self, col):
        return (PAGE_SIZE - HEADER.size) // COLUMNS[col].size

    def insert(self, row):
        for col, value in zip(COLUMNS, row):
            fmt = COLUMNS[col]
            slot = self.num_rows % self._per_page(col)
            if slot == 0:  # current page of this column is full -> start a new one
                self.pages[col].append(self.next_page)
                self.next_page += 1
            page_id = self.pages[col][-1]
            page = self.bpm.fetch_page(page_id)
            if col == "name":
                value = value.encode()[:20]
            fmt.pack_into(page, HEADER.size + slot * fmt.size, value)
            HEADER.pack_into(page, 0, slot + 1)
            self.bpm.unpin_page(page_id, is_dirty=True)
        self.num_rows += 1

    def scan_column(self, col):
        fmt = COLUMNS[col]
        for page_id in self.pages[col]:
            page = self.bpm.fetch_page(page_id)
            (count,) = HEADER.unpack_from(page, 0)
            values = [fmt.unpack_from(page, HEADER.size + i * fmt.size)[0] for i in range(count)]
            self.bpm.unpin_page(page_id)
            yield from values

    def get_row(self, idx):
        """Tuple reconstruction: one page read per column."""
        out = []
        for col, fmt in COLUMNS.items():
            per = self._per_page(col)
            page_id = self.pages[col][idx // per]
            page = self.bpm.fetch_page(page_id)
            out.append(fmt.unpack_from(page, HEADER.size + (idx % per) * fmt.size)[0])
            self.bpm.unpin_page(page_id)
        rid, name, gpa = out
        return rid, name.rstrip(b"\0").decode(), gpa


def convert_row_to_column(row_store, col_store):
    for row in row_store.scan():
        col_store.insert(row)
