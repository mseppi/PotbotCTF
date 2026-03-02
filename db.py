"""
Simple JSON-based database to replace MongoDB.
Stores data in the data/ directory as JSON files.
"""
import json
import pathlib
import threading

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)

_lock = threading.Lock()


def _path(name: str) -> pathlib.Path:
    return DATA_DIR / f"{name}.json"


def _load(name: str) -> list:
    p = _path(name)
    if p.exists():
        with open(p, "r") as f:
            return json.load(f)
    return []


def _save(name: str, data: list):
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


class Collection:
    """A minimal MongoDB-like collection backed by a JSON file."""

    def __init__(self, name: str):
        self.name = name

    def find(self) -> list:
        with _lock:
            return list(_load(self.name))

    def find_one(self, query: dict):
        with _lock:
            for doc in _load(self.name):
                if all(doc.get(k) == v for k, v in query.items()):
                    return doc
        return None

    def update(self, query: dict, update: dict, upsert: bool = False):
        with _lock:
            docs = _load(self.name)
            found = False
            for i, doc in enumerate(docs):
                if all(doc.get(k) == v for k, v in query.items()):
                    if "$set" in update:
                        doc.update(update["$set"])
                    else:
                        doc.update(update)
                    docs[i] = doc
                    found = True
                    break
            if not found and upsert:
                new_doc = dict(query)
                if "$set" in update:
                    new_doc.update(update["$set"])
                else:
                    new_doc.update(update)
                docs.append(new_doc)
            _save(self.name, docs)

    def remove(self, query: dict):
        with _lock:
            docs = _load(self.name)
            docs = [d for d in docs if not all(d.get(k) == v for k, v in query.items())]
            _save(self.name, docs)

    def drop(self):
        with _lock:
            _save(self.name, [])


class Database:
    """Access collections by name, like MongoDB: db['collection_name']"""

    def __getitem__(self, name: str) -> Collection:
        return Collection(name)


# Global database instances (mirrors the original NullCTF config_vars)
serverdb = Database()
teamdb = Database()
ctfs = Collection("ctftime_cache")
