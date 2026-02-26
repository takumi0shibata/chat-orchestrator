from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class JsonFileCache:
    def __init__(self, root: Path, ttl_hours: int) -> None:
        self.root = root
        self.ttl_hours = max(1, int(ttl_hours))
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, namespace: str, params: dict[str, Any]) -> dict[str, Any] | None:
        path = self._path_for(namespace=namespace, params=params)
        if not path.exists() or not self._is_fresh(path):
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def set(self, namespace: str, params: dict[str, Any], payload: dict[str, Any]) -> None:
        path = self._path_for(namespace=namespace, params=params)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return

    def _path_for(self, *, namespace: str, params: dict[str, Any]) -> Path:
        key_json = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(key_json.encode("utf-8")).hexdigest()
        return self.root / namespace / f"{digest}.json"

    def _is_fresh(self, path: Path) -> bool:
        age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return age <= timedelta(hours=self.ttl_hours)
