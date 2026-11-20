"""Starter API for Practice 10. Complete the functions and methods without changing their signatures."""


class QueryError(ValueError):
    """An invalid or unsupported query."""


class WriteError(Exception):
    """An invalid update or write."""


class TransactionAborted(Exception):
    pass


class SimulatedCrash(Exception):
    pass


# ================================================ Part A: the query language
def match(doc: dict, query: dict) -> bool:
    raise NotImplementedError("Implement MongoDB-style matching (see STUDENT_TASK.md, Part A)")


def apply_update(doc: dict, update: dict) -> dict:
    raise NotImplementedError("Return an updated copy; raise WriteError for invalid updates")


# ================================== Part B: the tenant-aware sharded store
class TenantStore:
    def __init__(self, shards=("s1", "s2")):
        self.crash_at = None
        self.last_shards = []
        raise NotImplementedError("Create the shards, the directory, and the coordinator log")

    def place_tenant(self, tenant: str, shard: str) -> None:
        raise NotImplementedError

    def shard_of(self, tenant: str) -> str:
        raise NotImplementedError

    def move_tenant(self, tenant: str, target: str) -> int:
        raise NotImplementedError

    def insert(self, tenant: str, collection: str, doc: dict):
        raise NotImplementedError

    def find(self, tenant: str, collection: str, query: dict | None = None) -> list[dict]:
        raise NotImplementedError

    def update(self, tenant: str, collection: str, query: dict, update: dict) -> int:
        raise NotImplementedError

    def transfer(self, from_tenant: str, to_tenant: str, amount) -> str:
        raise NotImplementedError("Two-phase commit across the tenants' shards")

    def fail(self, shard: str) -> None:
        raise NotImplementedError

    def restart(self, shard: str) -> list[str]:
        raise NotImplementedError

    def recover(self) -> dict[str, str]:
        raise NotImplementedError

    def in_doubt(self) -> list[str]:
        raise NotImplementedError
