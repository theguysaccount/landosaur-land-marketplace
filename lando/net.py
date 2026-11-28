"""Polite HTTP for agency crawls with per-origin robots checks, pacing, and bounded responses."""
import json
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


PERCENT_ESCAPE = re.compile(r"%([0-9a-fA-F]{2})")
UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def robots_path(path):
    encoded = urllib.parse.quote(path, safe="/?:@!$&'()*+,-.;=_~%")
    return PERCENT_ESCAPE.sub(
        lambda m: chr(int(m[1], 16)) if chr(int(m[1], 16)) in UNRESERVED else m[0].upper(),
        encoded,
    )


class Robots:
    def __init__(self, text):
        self.rules = []
        self.delay = 0
        agents, entries = [], []
        groups = []
        for raw in text.splitlines():
            key, _, value = raw.partition("#")[0].partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if entries:
                    groups.append((agents, entries))
                    agents, entries = [], []
                if value:
                    agents.append(value.lower())
            elif agents and key in ("allow", "disallow", "crawl-delay", "request-rate"):
                entries.append((key, value))
        groups.append((agents, entries))
        product = config.ROBOTS_AGENT.lower()
        matching = [entries for agents, entries in groups if product in agents]
        if not matching:
            matching = [entries for agents, entries in groups if "*" in agents]
        for entries in matching:
            for key, value in entries:
                if not value:
                    continue
                if key in ("allow", "disallow") and value.startswith("/"):
                    path = robots_path(value)
                    exact = path.endswith("$")
                    if exact:
                        path = path[:-1]
                    pattern = ".*".join(re.escape(piece) for piece in path.split("*"))
                    specificity = len(PERCENT_ESCAPE.sub("x", path).replace("*", ""))
                    self.rules.append((specificity, key == "allow", re.compile(pattern + ("$" if exact else ""))))
                elif key == "crawl-delay" and re.fullmatch(r"\d+(?:\.\d+)?", value):
                    self.delay = max(self.delay, float(value))
                elif key == "request-rate":
                    rate = re.fullmatch(r"(\d+)\s*/\s*(\d+)", value)
                    if rate and int(rate[1]):
                        self.delay = max(self.delay, int(rate[2]) / int(rate[1]))

    def allows(self, parts):
        path = robots_path((parts.path or "/") + ("?" + parts.query if parts.query else ""))
        matched = [(length, allow) for length, allow, regex in self.rules if regex.match(path)]
        return max(matched, default=(0, True))[1]


class Fetcher:
    def __init__(self, pause=1.0, tries=3, timeout=60, max_bytes=20000000, log=print):
        self.pause = pause
        self.tries = tries
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.log = log
        self.requests = 0
        self.robots = {}
        self._robots_locks = {}
        self._next_request = {}
        self._lock = threading.Lock()
        handlers = [NoRedirect()]
        if sys.platform == "darwin":
            try:
                import truststore
            except ImportError:
                pass
            else:
                # Use the macOS trust service to validate agencies with incomplete certificate chains.
                context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                handlers.append(urllib.request.HTTPSHandler(context=context))
        self._opener = urllib.request.build_opener(*handlers)

    def enable_cookies(self):
        """Retain site cookies for public forms that require a guest session."""
        if not any(isinstance(handler, urllib.request.HTTPCookieProcessor) for handler in self._opener.handlers):
            self._opener.add_handler(urllib.request.HTTPCookieProcessor())

    @staticmethod
    def _origin(parts):
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise FetchError("unsupported source URL")
        return "%s://%s" % (parts.scheme, parts.netloc.lower())

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        origin = self._origin(parts)
        with self._lock:
            lock = self._robots_locks.setdefault(origin, threading.Lock())
        with lock:
            if origin not in self.robots:
                try:
                    raw = self._get(origin + "/robots.txt", check_robots=False, tries=2, limit=512000)
                    text = raw.decode("utf-8-sig", "replace")
                    if re.match(r"\s*<", text):
                        raise FetchError("expected plain-text robots rules")
                    self.robots[origin] = Robots(text)
                except FetchError as exc:
                    if exc.status in (404, 410):
                        self.robots[origin] = Robots("")
                    else:
                        self.robots[origin] = FetchError("robots.txt unreadable for %s (%s)" % (origin, exc), exc.status)
            policy = self.robots[origin]
        if isinstance(policy, FetchError):
            raise policy
        return policy.allows(parts)

    def _request(self, url, origin, data, limit):
        policy = self.robots.get(origin)
        delay = max(self.pause, policy.delay if isinstance(policy, Robots) else 0)
        with self._lock:
            earliest = max(time.monotonic(), self._next_request.get(origin, 0))
            self._next_request[origin] = earliest + delay
            self.requests += 1
        time.sleep(max(0, earliest - time.monotonic()))
        req = urllib.request.Request(url, data=data, headers={"User-Agent": config.USER_AGENT, "Accept": "*/*"})
        with self._opener.open(req, timeout=self.timeout) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise FetchError("%s is larger than %d bytes" % (url, limit))
        return body

    def _download(self, url, check_robots, data, limit):
        for _ in range(6):
            parts = urllib.parse.urlsplit(url)
            origin = self._origin(parts)
            if check_robots and not self.allowed(url):
                raise FetchError("robots.txt disallows %s" % url)
            try:
                return self._request(url, origin, data, limit)
            except urllib.error.HTTPError as error:
                status, target = error.code, error.headers.get("Location")
                try:
                    # Esri's public feature-service gateways return "Invalid URL" for the
                    # nonexistent robots.txt route. Other access and robots errors fail closed.
                    if (not check_robots and status == 403 and parts.path == "/robots.txt"
                            and re.fullmatch(r"services\d*\.arcgis\.com", parts.hostname)
                            and error.read(64).strip() == b"Invalid URL"):
                        return b""
                finally:
                    error.close()
                if status not in (301, 302, 303, 307, 308) or not target:
                    raise FetchError("HTTP %s from %s%s" % (status, origin, parts.path), status) from error
                url = urllib.parse.urljoin(url, target)
                if status in (301, 302, 303):
                    data = None
        raise FetchError("too many redirects for %s" % url)

    def _get(self, url, check_robots=True, tries=None, data=None, limit=None):
        attempts = tries or self.tries
        for attempt in range(attempts):
            try:
                return self._download(url, check_robots, data, limit or self.max_bytes)
            except FetchError as exc:
                if exc.status is None or exc.status in (400, 401, 403, 404, 410, 451) or attempt + 1 == attempts:
                    raise
            except OSError as exc:
                if attempt + 1 == attempts:
                    raise FetchError("%s: %s" % (url, str(exc)[:200])) from exc
            time.sleep(3 * (attempt + 1))

    def text(self, url, *, form=None):
        body = urllib.parse.urlencode(form).encode() if form is not None else None
        return self._get(url, data=body).decode("utf-8-sig", "replace")

    def bytes(self, url):
        return self._get(url)

    def json(self, url, *, form=None, payload=None):
        if form is not None and payload is not None:
            raise ValueError("pass either form fields or a JSON payload")
        body = urllib.parse.urlencode(form).encode() if form is not None else None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode()
        try:
            return json.loads(self._get(url, data=body).decode("utf-8-sig", "replace"))
        except ValueError as exc:
            raise FetchError("%s did not return JSON (%s)" % (url, exc)) from exc
