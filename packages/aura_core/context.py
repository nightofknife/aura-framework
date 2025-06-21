from typing import Dict, Any


class Context:
    # ... (Context 类保持不变)
    def __init__(self):
        self._data: Dict[str, Any] = {}

    def set(self, key: str, value: Any):
        self._data[key.lower()] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key.lower(), default)

    def delete(self, key: str):
        self._data.pop(key.lower(), None)

    def __str__(self):
        return f"Context({list(self._data.keys())})"
