"""Persistent provider cooldowns and bounded, owner-isolated search snapshots."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import re
from time import monotonic, time

import portalocker

from app.core.exceptions import ExternalToolUnavailableError
from app.preprocessing.storage import digest, write_json


def response_ttl(headers, observed_at, elapsed, cap):
    """Conservatively respect RFC 9111 response freshness for private snapshots."""
    cc = headers.get("cache-control", "").lower()
    if (
        re.search(r"(?:^|,)\s*(?:no-store|no-cache)\b", cc)
        or headers.get("vary", "").strip() == "*"
    ):
        return 0

    def date(key, default):
        if key not in headers:
            return default
        value = parsedate_to_datetime(headers[key])
        if value.tzinfo is None:
            raise ValueError("ambiguous HTTP timezone")
        return value.timestamp()

    try:
        origin_date = date("date", observed_at)
        age = float(headers.get("age", "0"))
        if not math.isfinite(age) or age < 0:
            return 0
        age = max(0, observed_at - origin_date, age + elapsed)
        directives = re.findall(r"(?:^|,)\s*max-age\s*=\s*([^,]+)", cc)
        if directives:
            if len(directives) != 1 or not re.fullmatch(
                r'"?\d+"?', directives[0].strip()
            ):
                return 0
            lifetime = int(directives[0].strip().strip('"'))
        elif "max-age" in cc:
            return 0
        else:
            lifetime = date("expires", origin_date + cap) - origin_date
        return max(0, min(cap, lifetime - age))
    except (ValueError, TypeError, OverflowError):
        return 0


class ProviderState:
    def __init__(
        self, root, *, clock=time, ttl=600, max_entries=128, max_bytes=64 * 1024**2
    ):
        if any(type(v) is not int or v <= 0 for v in (ttl, max_entries, max_bytes)):
            raise ValueError("provider cache limits must be positive integers")
        self.root = Path(root).resolve()
        self.clock, self.ttl = clock, ttl
        self.max_entries, self.max_bytes = max_entries, max_bytes
        for name in ("cache", "cooldowns", "locks"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def path(self, kind, key):
        if kind not in {"cache", "cooldowns", "locks"} or not re.fullmatch(
            "[0-9a-f]{64}", key
        ):
            raise ValueError("invalid provider state identity")
        return self.root / kind / (key + ".json")

    def cooldown(self, key):
        try:
            row = json.loads(self.path("cooldowns", key).read_text(encoding="utf8"))
            if (
                row.get("kind") not in {"rate_limit", "unavailable"}
                or type(row.get("until")) not in (int, float)
                or not math.isfinite(row["until"])
            ):
                raise ValueError("invalid cooldown state")
            if row["until"] > self.clock():
                return row
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ExternalToolUnavailableError(
                "Provider cooldown state cannot be verified; no request sent"
            ) from exc
        return None

    def defer(self, key, seconds, kind):
        if (
            not math.isfinite(seconds)
            or seconds < 0
            or kind not in {"rate_limit", "unavailable"}
        ):
            raise ValueError("invalid provider cooldown")
        path = self.path("cooldowns", key)
        with portalocker.Lock(path.with_suffix(".lock"), timeout=5):
            previous = self.cooldown(key)
            until = self.clock() + seconds
            if previous and previous["until"] > until:
                return previous
            row = dict(until=until, kind=kind, observed_at=self.clock())
            write_json(path, row)
            return row

    def cached(self, key):
        try:
            row = json.loads(self.path("cache", key).read_text(encoding="utf8"))
            if row['fetched_at'] <= self.clock() < row["expires_at"] and row["output_sha256"] == digest(
                row["output"]
            ):
                return deepcopy(row)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def store(self, key, output, *, fetched_at, ttl):
        row = dict(
            output=output,
            output_sha256=digest(output),
            fetched_at=fetched_at,
            expires_at=fetched_at + min(ttl, self.ttl),
        )
        size = len(json.dumps(row, ensure_ascii=False).encode("utf8"))
        if ttl <= 0 or size > min(self.max_bytes, 8 * 1024**2):
            return
        # Only this cache's hash-named snapshots can be evicted. Raw EEG,
        # evidence stores and historical workflow outputs are never touched.
        with portalocker.Lock(self.root / "cache.lock", timeout=5):
            files = sorted(
                (
                    p
                    for p in (self.root / "cache").glob("*.json")
                    if re.fullmatch("[0-9a-f]{64}.json", p.name)
                ),
                key=lambda p: p.stat().st_mtime,
            )
            target = self.path("cache", key)
            files = [p for p in files if p != target]
            sizes = {p: p.stat().st_size for p in files}
            total = sum(sizes.values())
            while files and (
                len(files) >= self.max_entries or total + size > self.max_bytes
            ):
                oldest = files.pop(0)
                if oldest.resolve().parent != (self.root / "cache").resolve():
                    raise ValueError("provider cache entry escapes owned directory")
                oldest.unlink()
                total -= sizes[oldest]
            write_json(target, row)

    @asynccontextmanager
    async def coalesce(self, key, timeout):
        # A process-scoped file lock coalesces simultaneous identical searches,
        # including across registry instances; it is released on process exit.
        # Fixed shards keep coordination files bounded as queries accumulate.
        lock_key = digest(["search-lock-shard", int(key, 16) % 64])
        lock = portalocker.Lock(
            self.path("locks", lock_key),
            mode="a",
            timeout=0,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        )
        deadline = monotonic() + max(0.1, timeout)
        while True:
            try:
                lock.acquire()
                break
            except portalocker.exceptions.LockException:
                if monotonic() >= deadline:
                    raise ExternalToolUnavailableError(
                        "Provider search coordination slot is busy; no request sent"
                    )
                await asyncio.sleep(min(0.05, max(0, deadline - monotonic())))
        try:
            yield
        finally:
            lock.release()
