import os

PAGE_SIZE = 4096


class DiskManager:
    """The "library in the basement": reads and writes fixed-size pages in a file."""

    def __init__(self, path):
        mode = "r+b" if os.path.exists(path) else "w+b"
        self.f = open(path, mode)
        self.reads = 0
        self.writes = 0

    def read_page(self, page_id):
        self.reads += 1
        self.f.seek(page_id * PAGE_SIZE)
        data = self.f.read(PAGE_SIZE)
        return data.ljust(PAGE_SIZE, b"\0")  # never-written page -> zeros

    def write_page(self, page_id, data):
        assert len(data) == PAGE_SIZE
        self.writes += 1
        self.f.seek(page_id * PAGE_SIZE)
        self.f.write(data)

    def close(self):
        self.f.close()
