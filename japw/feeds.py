"""
Paginated feeds with read-ahead, shared by Pinterest, X, colour and For You.

A Feed wraps one cursor-paginated source. Everything fetched is kept in order and callers
read slices by offset — so re-opening a view is instant, "load more" is usually served from
memory, and the next page is already being fetched before the UI asks for it.

merged_pages() combines several feeds into one (interleaved, optionally filtered), pulling
from all of them in parallel — used for "All artists", colour feeds and For You.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from collections import OrderedDict
from typing import Callable

from japw.images import canonical_key

READ_AHEAD = 60          # keep this many items fetched beyond what was last requested
_MAX_EMPTY_PAGES = 4     # consecutive pages that added nothing (ads / filtered / dupes) before giving up
_WAIT_S = 30

# Three tiers so a merged feed (waits on sources) can never starve the source fetches it waits on.
_source_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="JAPW-feed")
_merge_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="JAPW-merge")
_call_pool = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="JAPW-call")

PageFetcher = Callable[[str | None], tuple[list[dict], str | None]]


class Feed:
    def __init__(self, fetch_page: PageFetcher, name: str = "", merged: bool = False) -> None:
        self._fetch_page = fetch_page
        self.name = name
        self.items: list[dict] = []
        self._keys: set[str] = set()
        self._bookmark: str | None = None
        self.exhausted = False
        self._pool = _merge_pool if merged else _source_pool
        self._inflight: concurrent.futures.Future | None = None
        self._lock = threading.Lock()
        self._wanted = 0
        self.created = time.monotonic()
        self.last_error: Exception | None = None

    # Runs on the pool.
    def _fetch_next(self) -> None:
        try:
            for _ in range(_MAX_EMPTY_PAGES):
                posts, bookmark = self._fetch_page(self._bookmark)
                added = 0
                with self._lock:
                    for p in posts:
                        k = canonical_key(p["urls"][0])
                        if k not in self._keys:
                            self._keys.add(k)
                            self.items.append(p)
                            added += 1
                    self._bookmark = bookmark
                    if not bookmark or bookmark == "-end-":
                        self.exhausted = True
                if added or self.exhausted:
                    break
            else:
                self.exhausted = True
            self.last_error = None
        except Exception as e:
            self.last_error = e
            raise
        finally:
            with self._lock:
                self._inflight = None
        self.prefetch()

    def _ensure_fetch_locked(self) -> concurrent.futures.Future | None:
        if self.exhausted:
            return None
        if self._inflight is None:
            self._inflight = self._pool.submit(self._fetch_next)
        return self._inflight

    def prefetch(self) -> None:
        """Fetch ahead in the background until READ_AHEAD items sit beyond the last request."""
        with self._lock:
            if self.last_error is None and len(self.items) < self._wanted + READ_AHEAD:
                self._ensure_fetch_locked()

    def get(self, offset: int, limit: int, min_count: int = 1) -> tuple[list[dict], bool]:
        """
        Return up to `limit` items from `offset`, waiting only until `min_count` are available
        (so the first page shows after one round trip). Second value: more may follow.
        """
        end = offset + limit
        need = offset + max(1, min(min_count, limit))
        deadline = time.monotonic() + _WAIT_S
        while True:
            with self._lock:
                self._wanted = max(self._wanted, end)
                if len(self.items) >= need or self.exhausted:
                    chunk = self.items[offset:end]
                    has_more = not self.exhausted or len(self.items) > end
                    break
                self.last_error = None
                fut = self._ensure_fetch_locked()
            if fut is not None:
                fut.result(timeout=max(1.0, deadline - time.monotonic()))
        self.prefetch()
        return chunk, has_more


def merged_pages(
    sources: list[Feed],
    keep: Callable[[dict], bool] | None = None,
    per_source: int = 25,
) -> PageFetcher:
    """
    A page fetcher that pulls the next `per_source` items from every live source in parallel,
    interleaves them round-robin (earlier sources first) and drops posts `keep` rejects.
    """
    offsets = [0] * len(sources)
    done = [False] * len(sources)

    def fetch(_bookmark):
        live = [i for i in range(len(sources)) if not done[i]]
        if not live:
            return [], None
        futures = {i: _call_pool.submit(sources[i].get, offsets[i], per_source) for i in live}
        chunks: dict[int, list[dict]] = {}
        errors = []
        for i, fut in futures.items():
            try:
                chunk, more = fut.result(timeout=_WAIT_S)
            except Exception as e:
                # One failing source shouldn't sink the rest.
                errors.append(e)
                done[i] = True
                continue
            offsets[i] += len(chunk)
            chunks[i] = chunk
            if not more or not chunk:
                done[i] = True
        if errors and not chunks:
            raise errors[0]
        out: list[dict] = []
        longest = max((len(c) for c in chunks.values()), default=0)
        for n in range(longest):
            for i in sorted(chunks):
                if n < len(chunks[i]) and (keep is None or keep(chunks[i][n])):
                    out.append(chunks[i][n])
        return out, None if all(done) else "more"

    return fetch


class FeedCache:
    """Small LRU of feeds keyed by e.g. ("search", "cats"); entries expire after ttl seconds."""

    def __init__(self, size: int = 24, ttl: float = 15 * 60) -> None:
        self._feeds: OrderedDict[tuple, Feed] = OrderedDict()
        self._size = size
        self._ttl = ttl
        # Re-entrant: building a merged feed looks up its source feeds in this same cache.
        self._lock = threading.RLock()

    def get(self, key: tuple, factory: Callable[[], Feed], fresh: bool = False, ttl: float | None = None) -> Feed:
        with self._lock:
            feed = self._feeds.get(key)
            max_age = self._ttl if ttl is None else ttl
            if feed is None or fresh or time.monotonic() - feed.created > max_age:
                feed = factory()
                self._feeds[key] = feed
            self._feeds.move_to_end(key)
            while len(self._feeds) > self._size:
                self._feeds.popitem(last=False)
            return feed

    def peek(self, key: tuple) -> Feed | None:
        with self._lock:
            return self._feeds.get(key)

    def drop(self, predicate: Callable[[tuple], bool]) -> None:
        with self._lock:
            for key in [k for k in self._feeds if predicate(k)]:
                del self._feeds[key]

    def clear(self) -> None:
        with self._lock:
            self._feeds.clear()


cache = FeedCache()


def shutdown() -> None:
    for pool in (_merge_pool, _call_pool, _source_pool):
        pool.shutdown(wait=False, cancel_futures=True)
