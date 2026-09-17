# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Outbound webhook transport hardened against SSRF.

Checking the URL only when the token is saved is not enough: DNS can change
afterwards (or answer differently on every lookup, "DNS rebinding") and an
endpoint can answer with a redirect to an internal address. Delivery therefore

1. resolves the host at send time and refuses loopback, private, link-local,
   shared (CGNAT), reserved, multicast and unspecified IPv4/IPv6 addresses,
   including IPv4 addresses embedded in IPv6 (mapped, 6to4, Teredo, NAT64);
2. connects to the validated IP itself (the URL is rewritten to the IP, the
   original host goes in the ``Host`` header and, for HTTPS, in SNI and the
   certificate hostname check), so a second DNS lookup cannot swap targets;
3. never follows redirects, ignores proxy settings from the environment and
   enforces short socket timeouts plus a total deadline for the whole call;
4. reads at most a few hundred bytes of the response body.
"""

import contextlib
import hashlib
import hmac
import ipaddress
import socket
import threading
import time
from urllib.parse import unquote, urlsplit, urlunsplit

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
except ImportError:  # pragma: no cover - requests ships with Odoo
    requests = None
    HTTPAdapter = object

ALLOWED_SCHEMES = ("http", "https")
DEFAULT_TIMEOUT = 5  # seconds, for the connection and each single read
DEFAULT_TOTAL_TIMEOUT = 10  # seconds, for the whole call (headers and body)
RESPONSE_BODY_LIMIT = 500
_NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")


class WebhookTargetError(ValueError):
    """The webhook URL cannot be used safely.

    ``reason`` is one of ``scheme``, ``host``, ``resolve``, ``blocked`` and
    ``ip`` carries the offending address for ``blocked``.
    """

    def __init__(self, reason, url=None, host=None, ip=None):
        self.reason = reason
        self.url = url
        self.host = host
        self.ip = ip
        super().__init__(f"{reason}: url={url!r} host={host!r} ip={ip!r}")


def _embedded_ipv4(ip):
    """Return the IPv4 addresses an IPv6 address tunnels to, if any."""
    if ip.version != 6:
        return []
    embedded = []
    if ip.ipv4_mapped:
        embedded.append(ip.ipv4_mapped)
    if ip.sixtofour:
        embedded.append(ip.sixtofour)
    if ip.teredo:
        embedded.extend(ip.teredo)
    if ip in _NAT64_NETWORK:
        embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return embedded


def is_public_ip(ip):
    """Return whether ``ip`` is a globally routable unicast address."""
    if isinstance(ip, str):
        ip = ipaddress.ip_address(ip.split("%", 1)[0])
    for inner in _embedded_ipv4(ip):
        if not is_public_ip(inner):
            return False
    if ip.version == 6 and ip in _NAT64_NETWORK:
        # The prefix itself is "reserved"; the embedded IPv4 decides.
        return True
    return bool(
        ip.is_global
        and not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    )


def _getaddrinfo(host, port):
    """Indirection so tests can fake DNS answers."""
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def parse_webhook_url(url):
    """Split ``url`` and return ``(parts, host, port)`` or raise."""
    parts = urlsplit((url or "").strip())
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise WebhookTargetError("scheme", url=url)
    try:
        host = parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:  # invalid port
        raise WebhookTargetError("host", url=url) from exc
    if not host:
        raise WebhookTargetError("host", url=url)
    return parts, host, port


def resolve_public_ips(host, port):
    """Resolve ``host`` and return its addresses, all verified public.

    Raises ``WebhookTargetError`` when resolution fails or when ANY answer
    is not public (a mixed answer is exactly what a rebinding attack uses).
    """
    try:
        infos = _getaddrinfo(host, port)
    except (OSError, UnicodeError) as exc:
        raise WebhookTargetError("resolve", host=host) from exc
    ips = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            continue
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise WebhookTargetError("resolve", host=host)
    for ip in ips:
        if not is_public_ip(ip):
            raise WebhookTargetError("blocked", host=host, ip=str(ip))
    return ips


def validate_webhook_url(url):
    """Validate scheme, host and resolved addresses of ``url``."""
    _parts, host, port = parse_webhook_url(url)
    return resolve_public_ips(host, port)


def sign_payload(key, payload):
    """HMAC-SHA256 hex signature of ``payload`` (str or bytes)."""
    if isinstance(payload, str):
        payload = payload.encode()
    if isinstance(key, str):
        key = key.encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


class _Watchdog:
    """Enforce a total deadline on one webhook call.

    Socket timeouts only bound each single ``recv``: an endpoint that drips
    one byte every few seconds keeps a call alive for as long as it likes
    (while the TLS handshake, the headers or the body are being read). When
    the deadline passes, the timer shuts the call's sockets down, which makes
    the blocked read return at once.
    """

    def __init__(self, seconds):
        self._lock = threading.Lock()
        self._sockets = []
        self.expired = False
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True

    def __enter__(self):
        _ACTIVE.watchdog = self
        self._timer.start()
        return self

    def __exit__(self, *exc_info):
        self._timer.cancel()
        _ACTIVE.watchdog = None
        return False

    @staticmethod
    def _shutdown(sock):
        with contextlib.suppress(OSError):  # already closed
            sock.shutdown(socket.SHUT_RDWR)

    def register(self, sock):
        with self._lock:
            self._sockets.append(sock)
            expired = self.expired
        if expired:
            self._shutdown(sock)

    def _expire(self):
        with self._lock:
            self.expired = True
            sockets = list(self._sockets)
        for sock in sockets:
            self._shutdown(sock)


# The watchdog of the call running in the current thread (connections are
# opened in the thread that sends the request).
_ACTIVE = threading.local()


def _register_socket(sock):
    watchdog = getattr(_ACTIVE, "watchdog", None)
    if watchdog is not None and sock is not None:
        watchdog.register(sock)
    return sock


if requests is not None:

    class _WatchedHTTPConnection(HTTPConnection):
        def _new_conn(self):
            return _register_socket(super()._new_conn())

    class _WatchedHTTPSConnection(HTTPSConnection):
        def _new_conn(self):
            return _register_socket(super()._new_conn())

    class _WatchedHTTPConnectionPool(HTTPConnectionPool):
        ConnectionCls = _WatchedHTTPConnection

    class _WatchedHTTPSConnectionPool(HTTPSConnectionPool):
        ConnectionCls = _WatchedHTTPSConnection

    _WATCHED_POOL_CLASSES = {
        "http": _WatchedHTTPConnectionPool,
        "https": _WatchedHTTPSConnectionPool,
    }
else:  # pragma: no cover
    _WATCHED_POOL_CLASSES = {}


class SafeWebhookAdapter(HTTPAdapter):
    """Transport adapter for webhook calls.

    Its sockets are registered with the call's watchdog. For HTTPS it
    connects to the pinned IP but verifies the real hostname:
    ``server_hostname`` drives SNI and ``assert_hostname`` the certificate
    check; both are standard urllib3 connection pool keywords.
    """

    def __init__(self, pinned_hostname=None, **kwargs):
        self._pinned_hostname = pinned_hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        if self._pinned_hostname:
            kwargs["server_hostname"] = self._pinned_hostname
            kwargs["assert_hostname"] = self._pinned_hostname
        result = super().init_poolmanager(*args, **kwargs)
        if _WATCHED_POOL_CLASSES:
            self.poolmanager.pool_classes_by_scheme = dict(_WATCHED_POOL_CLASSES)
        return result


def _read_limited(response, limit, deadline, watchdog=None):
    """Read at most ``limit`` bytes of the body, stopping at ``deadline``.

    When ``watchdog`` expired (it shut the socket down) the bytes read so far
    are returned instead of raising.
    """
    raw = getattr(response, "raw", None)
    if raw is None or not hasattr(raw, "read"):
        # Response without a live stream (already buffered, or mocked).
        data = (response.content or b"")[:limit]
    else:
        chunks = []
        size = 0
        read1 = getattr(raw, "read1", None)
        while size < limit and time.monotonic() < deadline:
            try:
                if read1 is not None:  # urllib3 >= 2: at most one socket read
                    chunk = read1(limit - size, decode_content=True)
                else:
                    chunk = raw.read(min(64, limit - size), decode_content=True)
            except Exception:
                if watchdog is None or not watchdog.expired:
                    raise
                break
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        data = b"".join(chunks)[:limit]
    if isinstance(data, str):
        return data[:limit]
    try:
        return data.decode(response.encoding or "utf-8", errors="replace")[:limit]
    except LookupError:  # unknown charset announced by the endpoint
        return data.decode("utf-8", errors="replace")[:limit]


def _close_response(response):
    # Response.close() dereferences ``raw``, which is None for buffered or
    # mocked responses (e.g. odoo.tests.common.MockHTTPClient).
    if getattr(response, "raw", None) is not None:
        response.close()


def post_webhook(
    url,
    payload,
    headers=None,
    timeout=DEFAULT_TIMEOUT,
    total_timeout=DEFAULT_TOTAL_TIMEOUT,
):
    """POST ``payload`` to ``url`` safely.

    Returns ``(status_code, body_excerpt)``. Raises ``WebhookTargetError``
    when the target is not allowed, ``requests.Timeout`` when the whole call
    exceeds ``total_timeout`` seconds and other ``requests`` exceptions on
    network failures.
    """
    if requests is None:
        raise RuntimeError("The python 'requests' library is not installed.")
    parts, host, port = parse_webhook_url(url)
    ip = resolve_public_ips(host, port)[0]
    ip_host = f"[{ip}]" if ip.version == 6 else str(ip)
    scheme = parts.scheme.lower()
    pinned_url = urlunsplit(
        (scheme, f"{ip_host}:{port}", parts.path or "/", parts.query, "")
    )
    request_headers = dict(headers or {})
    # Original authority (without credentials) so virtual hosts still work.
    request_headers["Host"] = parts.netloc.rpartition("@")[2]
    # A compressed body would need decoding work the deadline cannot bound
    # cleanly; the excerpt is only kept for diagnostics anyway.
    request_headers.setdefault("Accept-Encoding", "identity")
    auth = None
    if parts.username:
        auth = (unquote(parts.username), unquote(parts.password or ""))

    deadline = time.monotonic() + total_timeout
    with requests.Session() as session, _Watchdog(total_timeout) as watchdog:
        # Ignore HTTP(S)_PROXY / netrc from the environment: a proxy connects
        # on our behalf and could reach the internal addresses that were just
        # refused, and it would bypass the pinned TLS hostname check.
        session.trust_env = False
        session.mount("http://", SafeWebhookAdapter())
        session.mount("https://", SafeWebhookAdapter(pinned_hostname=host))
        try:
            response = session.post(
                pinned_url,
                data=payload.encode() if isinstance(payload, str) else payload,
                headers=request_headers,
                auth=auth,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as error:
            if watchdog.expired:
                raise _deadline_error(host, total_timeout) from error
            raise
        try:
            if watchdog.expired:
                # The sockets were shut down while the status line/headers
                # were being read. Depending on the platform the blocked read
                # then returns EOF instead of raising, so what was parsed may
                # be truncated: never trust that status.
                raise _deadline_error(host, total_timeout)
            # A body cut by the deadline still leaves a valid status: the
            # excerpt is only kept for diagnostics.
            body = _read_limited(response, RESPONSE_BODY_LIMIT, deadline, watchdog)
        finally:
            _close_response(response)
    return response.status_code, body


def _deadline_error(host, total_timeout):
    return requests.Timeout(
        f"Webhook call to {host} exceeded the total time limit of "
        f"{total_timeout} seconds."
    )
