"""Row-oriented storage (NSM): every page holds whole rows (id, name, gpa)."""
import struct

from disk_manager import PAGE_SIZE

ROW = struct.Struct("<i20sf")  # id (4) + name (20) + gpa (4) = 28 bytes
HEADER = struct.Struct("<H")  # first 2 bytes of a page = number of values in it
ROWS_PER_PAGE = (PAGE_SIZE - HEADER.size) // ROW.size  # 146


class RowStore:
    def __init__(self, bpm):
        self.bpm = bpm
        self.num_rows = 0
        self.num_pages = 0

    def insert(self, row):
        rid, name, gpa = row
        page_id, slot = divmod(self.num_rows, ROWS_PER_PAGE)
        page = self.bpm.fetch_page(page_id)
        ROW.pack_into(page, HEADER.size + slot * ROW.size, rid, name.encode()[:20], gpa)
        HEADER.pack_into(page, 0, slot + 1)
        self.bpm.unpin_page(page_id, is_dirty=True)
        self.num_rows += 1
        self.num_pages = page_id + 1

    def scan(self):
        for page_id in range(self.num_pages):
            page = self.bpm.fetch_page(page_id)
            (count,) = HEADER.unpack_from(page, 0)
            rows = [ROW.unpack_from(page, HEADER.size + i * ROW.size) for i in range(count)]
            self.bpm.unpin_page(page_id)
            for rid, name, gpa in rows:
                yield rid, name.rstrip(b"\0").decode(), gpa

    def get_row(self, idx):
        page_id, slot = divmod(idx, ROWS_PER_PAGE)
        page = self.bpm.fetch_page(page_id)
        rid, name, gpa = ROW.unpack_from(page, HEADER.size + slot * ROW.size)
        self.bpm.unpin_page(page_id)
        return rid, name.rstrip(b"\0").decode(), gpa
