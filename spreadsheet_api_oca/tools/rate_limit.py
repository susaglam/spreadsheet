# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Small in-process sliding-window rate limiter.

Odoo can run several threads in one process, so every access is serialised
with a lock. Buckets that saw no hit during the last window are pruned
periodically so the dictionary cannot grow without bound (the previous
implementation kept one list per token forever).

This limiter is per process: with ``workers > 1`` every worker keeps its own
counters, so the effective limit is ``limit * workers``. It is a brake against
brute force and runaway integrations, not an exact quota.
"""

import ipaddress
import threading
import time
from collections import deque


def client_ip_bucket(remote_addr):
    """Return the throttling bucket for a client address.

    IPv6 clients usually control a whole /64, so rotating addresses inside
    it would otherwise bypass a per-address throttle: they share one bucket.
    IPv4-mapped IPv6 addresses count as their IPv4 address. Anything that is
    not an IP address (e.g. a unix socket name) is used as is.
    """
    if not remote_addr:
        return None
    try:
        ip = ipaddress.ip_address(str(remote_addr).split("%", 1)[0])
    except ValueError:
        return str(remote_addr)
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class SlidingWindowLimiter:
    def __init__(self, window=60.0, prune_interval=60.0, max_keys=10000):
        self.window = float(window)
        self.prune_interval = float(prune_interval)
        self.max_keys = int(max_keys)
        self._hits = {}
        self._lock = threading.Lock()
        self._last_prune = None

    # ------------------------------------------------------------------
    # internals (call with the lock held)
    # ------------------------------------------------------------------
    def _trim(self, hits, now):
        threshold = now - self.window
        while hits and hits[0] <= threshold:
            hits.popleft()

    def _prune(self, now, force=False):
        if (
            not force
            and self._last_prune is not None
            and now - self._last_prune < self.prune_interval
        ):
            return
        self._last_prune = now
        for key in list(self._hits):
            hits = self._hits[key]
            self._trim(hits, now)
            if not hits:
                del self._hits[key]

    def _bucket(self, key, now):
        self._prune(now, force=len(self._hits) >= self.max_keys)
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()
        else:
            self._trim(hits, now)
        return hits

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def allow(self, key, limit, now=None):
        """Record one hit for ``key`` if it stays within ``limit``.

        Returns ``False`` (without recording) once ``limit`` hits were seen
        in the current window. A falsy ``limit`` means unlimited.
        """
        if not limit:
            return True
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._bucket(key, now)
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def hit(self, key, now=None):
        """Record one hit for ``key`` unconditionally."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._bucket(key, now).append(now)

    def is_limited(self, key, limit, now=None):
        """Return whether ``key`` already reached ``limit`` hits."""
        if not limit:
            return False
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return False
            self._trim(hits, now)
            return len(hits) >= limit

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def __len__(self):
        with self._lock:
            return len(self._hits)


# One limiter per concern, shared by every database served by this process.
# Keys always contain the database name so ids of different databases never
# share a bucket.
TOKEN_LIMITER = SlidingWindowLimiter()
FAILED_AUTH_LIMITER = SlidingWindowLimiter()
