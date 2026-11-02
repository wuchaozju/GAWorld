"""Bounded reuse of immutable SQLite embedding vectors.

Cache only decoded numeric data, never rows, hit lists or recall weights.
The exact stored JSON is part of the key, so external UPDATEs naturally miss;
the database path keeps independent worlds in separate cache namespaces.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from collections.abc import Iterable
from typing import NamedTuple

import numpy as np

VECTOR_CACHE_SIZE = 4096


def decode_vector_uncached(embedding_blob: str) -> np.ndarray:
    vector = np.array(json.loads(embedding_blob), dtype=np.float32)
    vector.flags.writeable = False
    return vector


class _CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int
    currsize: int


class _VectorCache:
    """LRU with a scan pre-touch so misses cannot evict upcoming hits.

    The caller pre-touches only the bounded prefix it will admit. For a
    resident's working set that fits the cache, this keeps its existing
    vectors newer than other residents' vectors before scanning begins.
    Concurrent scans can compete for space but never mutate cached arrays.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, str], np.ndarray] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def prepare(self, database_path: str, blobs: Iterable[str]) -> None:
        with self._lock:
            for blob in blobs:
                key = (database_path, blob)
                if key in self._entries:
                    self._entries.move_to_end(key)

    def __call__(self, database_path: str, embedding_blob: str) -> np.ndarray:
        key = (database_path, embedding_blob)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._hits += 1
                self._entries.move_to_end(key)
                return cached
            self._misses += 1
        # JSON parsing does not hold the shared lock. Two concurrent misses
        # may decode the same blob; the immutable values are interchangeable.
        vector = decode_vector_uncached(embedding_blob)
        with self._lock:
            self._entries[key] = vector
            self._entries.move_to_end(key)
            if len(self._entries) > VECTOR_CACHE_SIZE:
                self._entries.popitem(last=False)
        return vector

    def cache_clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = self._misses = 0

    def cache_info(self) -> _CacheInfo:
        with self._lock:
            return _CacheInfo(self._hits, self._misses, VECTOR_CACHE_SIZE, len(self._entries))


decode_vector = _VectorCache()
