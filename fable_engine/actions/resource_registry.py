"""Shared bounded registries for in-memory design resources."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
from threading import RLock
from typing import Any, Dict, Generic, Tuple, TypeVar


T = TypeVar("T")
MAX_DESIGN_RESOURCES = 64


class _RegistryCoordinator:
    """Tracks least-recently-used entries across all design registries."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._entries: "OrderedDict[Tuple[int, str], SharedResourceRegistry[Any]]" = OrderedDict()
        self._lock = RLock()

    def touch(self, registry: "SharedResourceRegistry[Any]", key: str) -> None:
        token = (id(registry), key)
        with self._lock:
            if token in self._entries:
                self._entries.move_to_end(token)
            else:
                self._entries[token] = registry
            while len(self._entries) > self.limit:
                (_, evicted_key), evicted_registry = self._entries.popitem(last=False)
                evicted_registry._evict(evicted_key)

    def discard(self, registry: "SharedResourceRegistry[Any]", key: str) -> None:
        with self._lock:
            self._entries.pop((id(registry), key), None)


_COORDINATOR = _RegistryCoordinator(MAX_DESIGN_RESOURCES)


class SharedResourceRegistry(MutableMapping[str, T], Generic[T]):
    """Dictionary-like LRU registry sharing one process-wide entry limit."""

    def __init__(self) -> None:
        self._data: Dict[str, T] = {}

    def __getitem__(self, key: str) -> T:
        value = self._data[key]
        _COORDINATOR.touch(self, key)
        return value

    def __setitem__(self, key: str, value: T) -> None:
        self._data[key] = value
        _COORDINATOR.touch(self, key)

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        _COORDINATOR.discard(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def _evict(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        for key in list(self._data):
            _COORDINATOR.discard(self, key)
        self._data.clear()
