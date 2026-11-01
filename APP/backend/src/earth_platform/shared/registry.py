"""Generic keyed registry used for every extension point (providers, tools, layers, panels).

Entries carry an *owner* so a plugin's contributions can be removed atomically on unload.
"""

from collections.abc import Iterator, Mapping

from earth_platform.shared.errors import ConflictError, NotFoundError

CORE_OWNER = "core"


class Registry[T]:
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, tuple[T, str]] = {}

    def register(self, key: str, item: T, *, owner: str = CORE_OWNER) -> None:
        if key in self._items:
            raise ConflictError(
                f"{self._kind} '{key}' is already registered by '{self._items[key][1]}'"
            )
        self._items[key] = (item, owner)

    def get(self, key: str) -> T:
        try:
            return self._items[key][0]
        except KeyError:
            raise NotFoundError(f"unknown {self._kind} '{key}'") from None

    def find(self, key: str) -> T | None:
        entry = self._items.get(key)
        return entry[0] if entry else None

    def owner_of(self, key: str) -> str | None:
        entry = self._items.get(key)
        return entry[1] if entry else None

    def items(self) -> Mapping[str, T]:
        return {k: v[0] for k, v in self._items.items()}

    def unregister_owner(self, owner: str) -> list[str]:
        removed = [k for k, (_, o) in self._items.items() if o == owner]
        for key in removed:
            del self._items[key]
        return removed

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
