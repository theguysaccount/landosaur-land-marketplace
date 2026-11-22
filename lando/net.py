"""Polite HTTP for the crawlers: an honest User-Agent, robots.txt, a pause between requests to the same host,
bounded retries and size limits. Standard library only."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from . import config


class FetchError(Exception):
    pass


class Fetcher(object):
    def __init__(self, pause=1.0, tries=3, timeout=60, max_bytes=20000000, log=print):
        self.pause = pause
        self.tries = tries
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.log = log
        self.last = {}
        self.robots = {}
        self.requests = 0

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        host = "%s://%s" % (parts.scheme, parts.netloc)
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                raw = self._get(host + "/robots.txt", check_robots=False, tries=2)
                rp.parse(raw.decode("utf-8", "replace").splitlines())
            except FetchError as exc:
                if "HTTP 4" in str(exc):   # no robots.txt: everything is allowed
                    rp.parse([])
                else:                      # cannot tell: do not crawl this host in this run
                    self.robots[host] = None
                    raise FetchError("robots.txt unreadable for %s (%s)" % (host, exc))
            self.robots[host] = rp
        rp = self.robots[host]
        if rp is None:
            raise FetchError("robots.txt unreadable for %s" % host)
        return rp.can_fetch(config.ROBOTS_AGENT, url)

    def _get(self, url, check_robots=True, tries=None, data=None):
        if check_robots and not self.allowed(url):
            raise FetchError("robots.txt disallows %s" % url)
        host = urllib.parse.urlsplit(url).netloc
        last = None
        for attempt in range(tries or self.tries):
            wait = self.pause - (time.time() - self.last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.time()
            self.requests += 1
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": config.USER_AGENT, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise FetchError("%s is larger than %d bytes" % (url, self.max_bytes))
                return body
            except urllib.error.HTTPError as exc:
                last = "HTTP %s" % exc.code
                if exc.code in (400, 401, 403, 404, 410):
                    break
            except FetchError:
                raise
            except Exception as exc:
                last = str(exc)[:200]
            time.sleep(3 * (attempt + 1))
        raise FetchError("%s: %s" % (url, last))

    def text(self, url):
        return self._get(url).decode("utf-8-sig", "replace")

    def json(self, url):
        try:
            return json.loads(self._get(url).decode("utf-8", "replace"))
        except ValueError as exc:
            raise FetchError("%s did not return JSON (%s)" % (url, exc))
