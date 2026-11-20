"""A small document database that speaks a useful subset of the MongoDB query language (MQL).

Documents are nested dicts and lists. Queries, updates, and pipelines use MongoDB's syntax, so
the same filter can be pasted into mongosh or PyMongo (see mongo_demo.py):

    db = DocumentDB()
    db["products"].insert_many([...])
    db["products"].find({"price": {"$lt": 50}, "tags": "sale"}, {"name": 1}, sort=[("price", -1)])
    db["products"].update_many({"stock": 0}, {"$set": {"status": "sold out"}})
    db["orders"].aggregate([{"$unwind": "$items"}, {"$group": {"_id": "$items.sku", "n": {"$sum": 1}}}])

Supported
  query    $eq $ne $gt $gte $lt $lte $in $nin $exists $regex $size $all $elemMatch $not $and $or $nor,
           dotted paths, implicit matching of array elements, {"field": None} matching missing fields
  update   $set $unset $inc $mul $min $max $push (with $each) $addToSet (with $each) $pull, upsert,
           whole-document replacement
  read     projection (include or exclude), sort, skip, limit, count_documents, distinct
  indexes  single-field (multikey on arrays), unique, explain() with docs examined
  pipeline $match $project $group ($sum $avg $min $max $push $addToSet $first $last) $sort $skip
           $limit $unwind $lookup $count

Comparisons follow MongoDB's rule that $gt / $lt only compare values of the same type family
(numbers with numbers, strings with strings, ...). Missing: transactions (see sharding.py),
the aggregation expression language beyond field paths, collation, and geospatial queries.

    python labs/lab10/docdb.py
"""

from __future__ import annotations

import copy
import itertools
import re
from numbers import Number

MISSING = object()


class DuplicateKeyError(Exception):
    pass


class WriteError(Exception):
    pass


# ------------------------------------------------------------- value helpers
def _is_number(v) -> bool:
    return isinstance(v, Number) and not isinstance(v, bool)


def type_rank(v) -> int:
    """MongoDB's cross-type sort order: null < numbers < strings < objects < arrays < booleans."""
    if v is None or v is MISSING:
        return 0
    if _is_number(v):
        return 1
    if isinstance(v, str):
        return 2
    if isinstance(v, dict):
        return 3
    if isinstance(v, list):
        return 4
    if isinstance(v, bool):
        return 5
    return 6


def sort_key(v):
    rank = type_rank(v)
    if rank == 0:
        return (0, 0)
    if rank in (3, 4):
        return (rank, repr(v))
    return (rank, v)


def bson_compare(a, b) -> int:
    """-1, 0, or 1 in MongoDB's order: by type first, then by value; arrays and documents
    compare element by element (field name, then value), and a shorter prefix sorts first."""
    ra, rb = type_rank(a), type_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 0:
        return 0
    if isinstance(a, list) or isinstance(a, dict):
        xs = list(a.items()) if isinstance(a, dict) else a
        ys = list(b.items()) if isinstance(b, dict) else b
        for x, y in zip(xs, ys):
            if isinstance(a, dict):
                c = bson_compare(x[0], y[0]) or bson_compare(x[1], y[1])
            else:
                c = bson_compare(x, y)
            if c:
                return c
        return (len(xs) > len(ys)) - (len(xs) < len(ys))
    return (a > b) - (a < b)


def comparable(a, b) -> bool:
    return (_is_number(a) and _is_number(b)) or (type(a) is type(b) and type_rank(a) in (2, 5))


def resolve(doc, path: str) -> list:
    """All values a dotted path reaches. Arrays on the way are entered element by element,
    and a numeric part ("items.0") indexes an array, as in MongoDB."""
    values = [doc]
    for part in path.split("."):
        found = []
        for value in values:
            if isinstance(value, dict):
                if part in value:
                    found.append(value[part])
            elif isinstance(value, list):
                if part.isdigit():
                    if int(part) < len(value):
                        found.append(value[int(part)])
                else:
                    found += [e[part] for e in value if isinstance(e, dict) and part in e]
        values = found
    return values


def get_path(doc, path: str, default=MISSING):
    """The single value at a dotted path (no array fan-out), used by sort, projection and $group."""
    value = doc
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return default
    return value


def _candidates(values: list) -> list:
    """A query on an array field matches the array itself or any of its elements."""
    out = []
    for v in values:
        out.append(v)
        if isinstance(v, list):
            out += v
    return out


# ------------------------------------------------------------------- matching
def matches(doc: dict, query: dict) -> bool:
    for key, condition in query.items():
        if key == "$and":
            if not all(matches(doc, q) for q in condition):
                return False
        elif key == "$or":
            if not any(matches(doc, q) for q in condition):
                return False
        elif key == "$nor":
            if any(matches(doc, q) for q in condition):
                return False
        elif key.startswith("$"):
            raise ValueError(f"unknown top-level operator {key}")
        elif not _match_field(resolve(doc, key), condition):
            return False
    return True


def _is_operator_dict(condition) -> bool:
    return isinstance(condition, dict) and condition and all(k.startswith("$") for k in condition)


def _match_field(values: list, condition) -> bool:
    if _is_operator_dict(condition):
        return all(_apply_op(values, op, arg, condition) for op, arg in condition.items())
    return _eq(values, condition)


def _eq(values: list, target) -> bool:
    if target is None and not values:
        return True  # {"field": None} also matches documents without the field
    return any(v == target and type_rank(v) == type_rank(target) for v in _candidates(values))


def _apply_op(values: list, op: str, arg, whole: dict) -> bool:
    candidates = _candidates(values)
    if op == "$eq":
        return _eq(values, arg)
    if op == "$ne":
        return not _eq(values, arg)
    if op in ("$gt", "$gte", "$lt", "$lte"):
        if arg is None:  # null is only "equal" to null or a missing field
            return op in ("$gte", "$lte") and _eq(values, None)
        accept = {"$gt": lambda c: c > 0, "$gte": lambda c: c >= 0,
                  "$lt": lambda c: c < 0, "$lte": lambda c: c <= 0}[op]
        if isinstance(arg, list):  # arrays compare as whole arrays, element by element
            return any(isinstance(v, list) and accept(bson_compare(v, arg)) for v in values)
        return any(comparable(v, arg) and accept(bson_compare(v, arg)) for v in candidates)
    if op == "$in":
        if not isinstance(arg, list):
            raise ValueError("$in needs a list")
        return any(_eq(values, a) for a in arg)
    if op == "$nin":
        return not any(_eq(values, a) for a in arg)
    if op == "$exists":
        return bool(values) == bool(arg)
    if op == "$regex":
        pattern = re.compile(arg, re.IGNORECASE if "i" in whole.get("$options", "") else 0)
        return any(isinstance(v, str) and pattern.search(v) for v in candidates)
    if op == "$options":
        return True  # read together with $regex
    if op == "$size":
        return any(isinstance(v, list) and len(v) == arg for v in values)
    if op == "$all":
        return any(isinstance(v, list) and all(_eq([v], a) for a in arg) for v in values)
    if op == "$elemMatch":
        for v in values:
            if isinstance(v, list):
                for element in v:
                    if isinstance(element, dict) and not _is_operator_dict(arg) and matches(element, arg):
                        return True
                    if _is_operator_dict(arg) and _match_field([element], arg):
                        return True
        return False
    if op == "$not":
        return not _match_field(values, arg)
    raise ValueError(f"unknown query operator {op}")


# -------------------------------------------------------------------- updates
def _check_document(doc, top=True) -> None:
    if isinstance(doc, dict):
        for key, value in doc.items():
            if not isinstance(key, str) or key.startswith("$") or "." in key:
                raise WriteError(f"invalid field name {key!r}")
            _check_document(value, False)
    elif isinstance(doc, list):
        for value in doc:
            _check_document(value, False)


def _parent(doc: dict, path: str, create: bool):
    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        if isinstance(node, list) and part.isdigit():
            node = node[int(part)]
            continue
        if part not in node:
            if not create:
                return None, parts[-1]
            node[part] = {}
        node = node[part]
        if not isinstance(node, (dict, list)):
            raise WriteError(f"cannot create field inside non-document at {part!r}")
    return node, parts[-1]


def _set(doc, path, value) -> None:
    parent, last = _parent(doc, path, create=True)
    if isinstance(parent, list):
        parent[int(last)] = value
    else:
        parent[last] = value


def apply_update(doc: dict, update: dict) -> dict:
    """Return the updated copy of doc. Raises WriteError for invalid updates."""
    if not update:
        raise WriteError("empty update")
    new = copy.deepcopy(doc)
    paths = [p for op, fields in update.items() if op.startswith("$") for p in fields]
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if a == b or a.startswith(b + ".") or b.startswith(a + "."):
                raise WriteError(f"Updating the path '{b}' would create a conflict at '{a}'")
    if not any(k.startswith("$") for k in update):  # replacement
        _check_document(update)
        replacement = copy.deepcopy(update)
        if "_id" in replacement and replacement["_id"] != doc.get("_id"):
            raise WriteError("_id is immutable")
        replacement["_id"] = doc.get("_id")
        return replacement
    for op, fields in update.items():
        if not op.startswith("$"):
            raise WriteError("cannot mix operators and plain fields in one update")
        for path, arg in fields.items():
            if path == "_id" or path.startswith("_id."):
                raise WriteError("_id is immutable")
            current = get_path(new, path)
            if op == "$set":
                _check_document(arg)
                _set(new, path, copy.deepcopy(arg))
            elif op == "$unset":
                parent, last = _parent(new, path, create=False)
                if isinstance(parent, dict):
                    parent.pop(last, None)
            elif op in ("$inc", "$mul"):
                if not _is_number(arg) or (current is not MISSING and not _is_number(current)):
                    raise WriteError(f"{op} needs numbers")
                base = 0 if current is MISSING else current
                _set(new, path, base + arg if op == "$inc" else (base * arg if current is not MISSING else 0))
            elif op in ("$min", "$max"):
                if current is MISSING or (comparable(arg, current) and
                                          (arg < current if op == "$min" else arg > current)):
                    _set(new, path, arg)
            elif op in ("$push", "$addToSet"):
                items = arg["$each"] if isinstance(arg, dict) and "$each" in arg else [arg]
                array = [] if current is MISSING else current
                if not isinstance(array, list):
                    raise WriteError(f"{op} needs an array field")
                array = list(array)
                for item in items:
                    if op == "$push" or item not in array:
                        array.append(copy.deepcopy(item))
                _set(new, path, array)
            elif op == "$pull":
                if current is MISSING:
                    continue
                if not isinstance(current, list):
                    raise WriteError("$pull needs an array field")
                keep = []
                for element in current:
                    if isinstance(arg, dict) and isinstance(element, dict) and not _is_operator_dict(arg):
                        drop = matches(element, arg)
                    else:
                        drop = _match_field([element], arg)
                    if not drop:
                        keep.append(element)
                _set(new, path, keep)
            else:
                raise WriteError(f"unknown update operator {op}")
    return new


# ----------------------------------------------------------------- projection
def project(doc: dict, projection: dict | None) -> dict:
    if not projection:
        return copy.deepcopy(doc)
    include_id = projection.get("_id", 1)
    fields = {k: v for k, v in projection.items() if k != "_id"}
    if fields and len({bool(v) for v in fields.values()}) > 1:
        raise ValueError("projection cannot mix inclusion and exclusion")
    if fields and all(fields.values()):  # inclusion
        out = {}
        if include_id and "_id" in doc:
            out["_id"] = doc["_id"]
        for path in fields:
            value = get_path(doc, path)
            if value is not MISSING:
                _set(out, path, copy.deepcopy(value))
        return out
    out = copy.deepcopy(doc)  # exclusion
    for path in fields:
        parent, last = _parent(out, path, create=False)
        if isinstance(parent, dict):
            parent.pop(last, None)
    if not include_id:
        out.pop("_id", None)
    return out


# ---------------------------------------------------------------- collection
class Collection:
    def __init__(self, name: str, db: "DocumentDB") -> None:
        self.name = name
        self.db = db
        self.docs: dict[object, dict] = {}  # _id -> document, in insertion order
        self.indexes: dict[str, dict] = {}  # field -> {"unique": bool, "map": {value: set(_id)}}
        self.last_plan: dict = {}

    # ------------------------------------------------------------- indexes
    @staticmethod
    def _index_keys(doc, field) -> list:
        keys = []
        for v in _candidates(resolve(doc, field)) or [None]:
            if not isinstance(v, (dict, list)):
                keys.append(v)
        return list(dict.fromkeys(keys))

    def create_index(self, field: str, unique: bool = False) -> str:
        entry = {"unique": unique, "map": {}}
        for _id, doc in self.docs.items():
            for k in self._index_keys(doc, field):
                ids = entry["map"].setdefault((type_rank(k), k), set())
                if unique and ids:
                    raise DuplicateKeyError(f"duplicate key {k!r} for unique index on {field}")
                ids.add(_id)
        self.indexes[field] = entry
        return f"{field}_1"

    def _index_add(self, doc) -> None:
        for field, entry in self.indexes.items():
            for k in self._index_keys(doc, field):
                ids = entry["map"].get((type_rank(k), k), set())
                if entry["unique"] and ids - {doc["_id"]}:
                    raise DuplicateKeyError(f"duplicate key {k!r} for unique index on {field}")
        for field, entry in self.indexes.items():
            for k in self._index_keys(doc, field):
                entry["map"].setdefault((type_rank(k), k), set()).add(doc["_id"])

    def _index_remove(self, doc) -> None:
        for field, entry in self.indexes.items():
            for k in self._index_keys(doc, field):
                entry["map"].get((type_rank(k), k), set()).discard(doc["_id"])

    def _plan(self, query: dict) -> tuple[str, list]:
        """Use an index for a top-level equality or $in on an indexed field, else scan everything."""
        for field, condition in query.items():
            if field in self.indexes:
                if not _is_operator_dict(condition) and not isinstance(condition, (dict, list)):
                    values = [condition]
                elif _is_operator_dict(condition) and set(condition) <= {"$eq", "$in"}:
                    values = [condition["$eq"]] if "$eq" in condition else list(condition["$in"])
                else:
                    continue
                if any(isinstance(v, (dict, list)) for v in values) or None in values:
                    continue
                ids = set()
                for v in values:
                    ids |= self.indexes[field]["map"].get((type_rank(v), v), set())
                ordered = [i for i in self.docs if i in ids]
                return f"IXSCAN {field}", ordered
        return "COLLSCAN", list(self.docs)

    # -------------------------------------------------------------- writes
    def _new_id(self):
        return f"oid{next(self.db.id_counter):06d}"

    def insert_one(self, doc: dict) -> object:
        if not isinstance(doc, dict):
            raise WriteError("documents must be dicts")
        _check_document(doc)
        doc = copy.deepcopy(doc)
        doc.setdefault("_id", self._new_id())
        if doc["_id"] in self.docs:
            raise DuplicateKeyError(f"duplicate _id {doc['_id']!r}")
        self._index_add(doc)
        self.docs[doc["_id"]] = doc
        return doc["_id"]

    def insert_many(self, docs: list[dict]) -> list:
        return [self.insert_one(d) for d in docs]

    def _replace_stored(self, old: dict, new: dict) -> None:
        self._index_remove(old)
        try:
            self._index_add(new)
        except DuplicateKeyError:
            self._index_add(old)
            raise
        self.docs[old["_id"]] = new

    def update_one(self, query: dict, update: dict, upsert: bool = False) -> dict:
        return self._update(query, update, upsert, many=False)

    def update_many(self, query: dict, update: dict, upsert: bool = False) -> dict:
        return self._update(query, update, upsert, many=True)

    def replace_one(self, query: dict, replacement: dict, upsert: bool = False) -> dict:
        if any(k.startswith("$") for k in replacement):
            raise WriteError("replacement documents cannot contain update operators")
        return self._update(query, replacement, upsert, many=False)

    def _update(self, query, update, upsert, many) -> dict:
        matched = modified = 0
        for _id in self._plan(query)[1]:
            doc = self.docs[_id]
            if not matches(doc, query):
                continue
            matched += 1
            new = apply_update(doc, update)
            if new != doc:
                self._replace_stored(doc, new)
                modified += 1
            if not many:
                break
        upserted = None
        if matched == 0 and upsert:
            seed = {k: v for k, v in query.items() if not k.startswith("$") and not _is_operator_dict(v)}
            base = {}
            for path, value in seed.items():
                _set(base, path, copy.deepcopy(value))
            new = apply_update(base, update) if any(k.startswith("$") for k in update) else copy.deepcopy(update)
            if "_id" in seed:
                new["_id"] = seed["_id"]
            upserted = self.insert_one(new)
        return {"matched": matched, "modified": modified, "upserted_id": upserted}

    def delete_one(self, query: dict) -> int:
        return self._delete(query, many=False)

    def delete_many(self, query: dict) -> int:
        return self._delete(query, many=True)

    def _delete(self, query, many) -> int:
        deleted = 0
        for _id in self._plan(query)[1]:
            doc = self.docs[_id]
            if matches(doc, query):
                self._index_remove(doc)
                del self.docs[_id]
                deleted += 1
                if not many:
                    break
        return deleted

    # --------------------------------------------------------------- reads
    def find(self, query: dict | None = None, projection: dict | None = None, *,
             sort: list[tuple[str, int]] | None = None, skip: int = 0, limit: int = 0) -> list[dict]:
        query = query or {}
        plan, candidates = self._plan(query)
        result = [self.docs[i] for i in candidates if matches(self.docs[i], query)]
        self.last_plan = {"plan": plan, "docsExamined": len(candidates), "nReturned": len(result)}
        for field, direction in reversed(sort or []):
            result.sort(key=lambda d: sort_key(get_path(d, field, None)), reverse=direction < 0)
        result = result[skip:]
        if limit:
            result = result[:limit]
        self.last_plan["nReturned"] = len(result)
        return [project(d, projection) for d in result]

    def find_one(self, query: dict | None = None, projection: dict | None = None):
        found = self.find(query, projection, limit=1)
        return found[0] if found else None

    def count_documents(self, query: dict | None = None) -> int:
        return len(self.find(query))

    def distinct(self, field: str, query: dict | None = None) -> list:
        values = []
        for doc in self.find(query):
            for v in _candidates(resolve(doc, field)):
                if not isinstance(v, list) and v not in values:
                    values.append(v)
        return sorted(values, key=sort_key)

    def explain(self, query: dict) -> dict:
        self.find(query)
        return dict(self.last_plan)

    def aggregate(self, pipeline: list[dict]) -> list[dict]:
        return run_pipeline([copy.deepcopy(d) for d in self.docs.values()], pipeline, self.db)


# ------------------------------------------------------------------ pipeline
def _field_value(doc, path: str):
    """A field path as the aggregation language reads it: through an array of documents it
    returns the list of their values ("$items.sku" -> ["p1", "p2"])."""
    value = doc
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part, MISSING)
        elif isinstance(value, list):
            value = [e[part] for e in value if isinstance(e, dict) and part in e]
        else:
            return MISSING
        if value is MISSING:
            return MISSING
    return value


def _value(doc, expression):
    if isinstance(expression, str) and expression.startswith("$"):
        value = _field_value(doc, expression[1:])
        return None if value is MISSING else value
    if isinstance(expression, dict):
        return {k: _value(doc, v) for k, v in expression.items()}
    return expression


def _group(docs, spec):
    groups: dict = {}
    order = []
    for doc in docs:
        key = _value(doc, spec["_id"])
        marker = repr(key)
        if marker not in groups:
            groups[marker] = {"_id": key, "_docs": []}
            order.append(marker)
        groups[marker]["_docs"].append(doc)
    out = []
    for marker in order:
        group = groups[marker]
        row = {"_id": group["_id"]}
        for name, accumulator in spec.items():
            if name == "_id":
                continue
            (op, expr), = accumulator.items()
            values = [_value(d, expr) for d in group["_docs"]]
            numbers = [v for v in values if _is_number(v)]
            if op == "$sum":
                row[name] = sum(numbers)
            elif op == "$avg":
                row[name] = sum(numbers) / len(numbers) if numbers else None
            elif op in ("$min", "$max"):
                present = [v for v in values if v is not None]
                row[name] = (min if op == "$min" else max)(present, key=sort_key) if present else None
            elif op == "$push":
                row[name] = values
            elif op == "$addToSet":
                unique = []
                for v in values:
                    if v not in unique:
                        unique.append(v)
                row[name] = unique
            elif op == "$first":
                row[name] = values[0]
            elif op == "$last":
                row[name] = values[-1]
            else:
                raise ValueError(f"unknown accumulator {op}")
        out.append(row)
    return out


def run_pipeline(docs: list[dict], pipeline: list[dict], db: "DocumentDB | None" = None, *,
                 lookup_source=None, lookup_filter: dict | None = None) -> list[dict]:
    """Run stages in order. lookup_source(name) may supply the documents of a $lookup collection
    (a sharded router gathers them from every shard); lookup_filter restricts them (tenant scope)."""
    for stage in pipeline:
        (name, spec), = stage.items()
        if name == "$match":
            docs = [d for d in docs if matches(d, spec)]
        elif name == "$project":
            computed = {k: v for k, v in spec.items() if isinstance(v, (str, dict)) and v not in (0, 1)}
            plain = {k: v for k, v in spec.items() if k not in computed}
            out = []
            for d in docs:
                row = project(d, plain) if plain else ({"_id": d.get("_id")} if spec.get("_id", 1) else {})
                for k, expr in computed.items():
                    row[k] = _value(d, expr)
                out.append(row)
            docs = out
        elif name == "$group":
            docs = _group(docs, spec)
        elif name == "$sort":
            for field, direction in reversed(list(spec.items())):
                docs.sort(key=lambda d: sort_key(get_path(d, field, None)), reverse=direction < 0)
        elif name == "$skip":
            docs = docs[spec:]
        elif name == "$limit":
            docs = docs[:spec]
        elif name == "$unwind":
            path = spec[1:] if isinstance(spec, str) else spec["path"][1:]
            out = []
            for d in docs:
                array = get_path(d, path)
                if isinstance(array, list):
                    for element in array:
                        row = copy.deepcopy(d)
                        _set(row, path, element)
                        out.append(row)
            docs = out
        elif name == "$lookup":
            if lookup_source is not None:
                foreign_docs = lookup_source(spec["from"])
            elif db is not None:
                foreign_docs = list(db[spec["from"]].docs.values())
            else:
                raise ValueError("$lookup needs a database")
            if lookup_filter:
                foreign_docs = [f for f in foreign_docs if matches(f, lookup_filter)]
            out = []
            for d in docs:
                local = _field_value(d, spec["localField"])  # through arrays, like MongoDB
                local = None if local is MISSING else local
                keys = local if isinstance(local, list) else [local]
                joined = [copy.deepcopy(f) for f in foreign_docs
                          if any(_eq(resolve(f, spec["foreignField"]), k) for k in keys)]
                row = dict(d)
                row[spec["as"]] = joined
                out.append(row)
            docs = out
        elif name == "$count":
            docs = [{spec: len(docs)}]
        else:
            raise ValueError(f"unsupported stage {name}")
    return docs


class DocumentDB:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}
        self.id_counter = itertools.count(1)

    def __getitem__(self, name: str) -> Collection:
        if name not in self.collections:
            self.collections[name] = Collection(name, self)
        return self.collections[name]

    def list_collection_names(self) -> list[str]:
        return sorted(self.collections)

    def drop_collection(self, name: str) -> None:
        self.collections.pop(name, None)


# -------------------------------------------------------------------- demo
PRODUCTS = [
    {"_id": "p1", "name": "Laptop", "category": "computers", "price": 950, "stock": 4,
     "tags": ["sale", "work"], "specs": {"ram_gb": 16, "cpu": "i7"}, "ratings": [5, 4, 5]},
    {"_id": "p2", "name": "Mouse", "category": "accessories", "price": 15, "stock": 0,
     "tags": ["work"], "ratings": [3, 4]},
    {"_id": "p3", "name": "Monitor", "category": "computers", "price": 210, "stock": 12,
     "tags": ["sale"], "specs": {"size_in": 27}, "ratings": []},
    {"_id": "p4", "name": "Keyboard", "category": "accessories", "price": 45, "stock": 30,
     "tags": ["work", "rgb"], "ratings": [4]},
    {"_id": "p5", "name": "Tablet", "category": "computers", "price": 330, "stock": 7,
     "tags": [], "specs": {"ram_gb": 8}},
]
ORDERS = [
    {"_id": "o1", "customer": "sara", "items": [{"sku": "p1", "qty": 1}, {"sku": "p2", "qty": 2}], "status": "paid"},
    {"_id": "o2", "customer": "omar", "items": [{"sku": "p4", "qty": 1}], "status": "paid"},
    {"_id": "o3", "customer": "sara", "items": [{"sku": "p3", "qty": 2}, {"sku": "p4", "qty": 1}], "status": "new"},
]


def show(title, value) -> None:
    print(f"  {title}\n    -> {value}")


def main() -> None:
    db = DocumentDB()
    products, orders = db["products"], db["orders"]
    products.insert_many(PRODUCTS)
    orders.insert_many(ORDERS)

    print("Queries")
    show('find({"price": {"$lt": 100}}, {"name": 1, "_id": 0})',
         products.find({"price": {"$lt": 100}}, {"name": 1, "_id": 0}))
    show('find({"tags": "sale"})  (matches any array element)', [p["_id"] for p in products.find({"tags": "sale"})])
    show('find({"specs.ram_gb": {"$gte": 16}})  (dotted path)', [p["_id"] for p in products.find({"specs.ram_gb": {"$gte": 16}})])
    show('find({"specs": {"$exists": False}})', [p["_id"] for p in products.find({"specs": {"$exists": False}})])
    show('find({"$or": [{"stock": 0}, {"tags": {"$size": 0}}]})',
         [p["_id"] for p in products.find({"$or": [{"stock": 0}, {"tags": {"$size": 0}}]})])
    show('find({"ratings": {"$elemMatch": {"$gte": 5}}})', [p["_id"] for p in products.find({"ratings": {"$elemMatch": {"$gte": 5}}})])
    show('find({"items": {"$elemMatch": {"sku": "p4", "qty": {"$gte": 1}}}}) on orders',
         [o["_id"] for o in orders.find({"items": {"$elemMatch": {"sku": "p4", "qty": {"$gte": 1}}}})])
    show('find({"name": {"$regex": "^m", "$options": "i"}}, sort=[("price", -1)])',
         [p["name"] for p in products.find({"name": {"$regex": "^m", "$options": "i"}}, sort=[("price", -1)])])

    print("\nUpdates")
    show('update_many({"stock": 0}, {"$set": {"status": "sold out"}})',
         products.update_many({"stock": 0}, {"$set": {"status": "sold out"}}))
    show('update_one({"_id": "p4"}, {"$inc": {"stock": -1}, "$push": {"ratings": 5}, "$addToSet": {"tags": "work"}})',
         products.update_one({"_id": "p4"}, {"$inc": {"stock": -1}, "$push": {"ratings": 5}, "$addToSet": {"tags": "work"}}))
    print(f"    p4 now: {products.find_one({'_id': 'p4'}, {'stock': 1, 'ratings': 1, 'tags': 1})}")
    show('update_one({"_id": "p9"}, {"$set": {"name": "Webcam", "price": 60}}, upsert=True)',
         products.update_one({"_id": "p9"}, {"$set": {"name": "Webcam", "price": 60}}, upsert=True))

    print("\nIndexes")
    products.insert_many([{"_id": f"x{i}", "category": f"c{i % 50}", "price": i} for i in range(2000)])
    show('explain({"category": "computers"}) without an index', products.explain({"category": "computers"}))
    products.create_index("category")
    show('explain({"category": "computers"}) with an index', products.explain({"category": "computers"}))
    products.delete_many({"_id": {"$regex": "^x"}})

    print("\nAggregation")
    show("units sold per product in paid orders ($match, $unwind, $lookup, $group, $sort)", orders.aggregate([
        {"$match": {"status": "paid"}},
        {"$unwind": "$items"},
        {"$lookup": {"from": "products", "localField": "items.sku", "foreignField": "_id", "as": "product"}},
        {"$unwind": "$product"},
        {"$project": {"sku": "$items.sku", "qty": "$items.qty", "price": "$product.price"}},
        {"$group": {"_id": "$sku", "units": {"$sum": "$qty"}, "unit_price": {"$first": "$price"}}},
        {"$sort": {"units": -1, "_id": 1}},
    ]))
    show("average price and count per category", products.aggregate([
        {"$group": {"_id": "$category", "avg_price": {"$avg": "$price"}, "n": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]))


if __name__ == "__main__":
    main()
