import os
import time

from skills.boj_timeseries_insight.cache import JsonFileCache


def test_cache_hit_within_ttl(tmp_path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_hours=24)
    params = {"k": "v"}
    payload = {"ok": True}
    cache.set("sample", params, payload)

    loaded = cache.get("sample", params)
    assert loaded == payload


def test_cache_expired(tmp_path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_hours=1)
    params = {"k": "v"}
    payload = {"ok": True}
    cache.set("sample", params, payload)

    path = next((tmp_path / "sample").glob("*.json"))
    old = time.time() - 2 * 3600
    os.utime(path, (old, old))

    assert cache.get("sample", params) is None


def test_cache_broken_json_returns_none(tmp_path) -> None:
    cache = JsonFileCache(root=tmp_path, ttl_hours=24)
    params = {"k": "v"}
    payload = {"ok": True}
    cache.set("sample", params, payload)

    path = next((tmp_path / "sample").glob("*.json"))
    path.write_text("{not-json", encoding="utf-8")

    assert cache.get("sample", params) is None
