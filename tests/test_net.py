import io
from email.message import Message
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit

from lando.net import FetchError, Fetcher, Robots


class RobotsTest(unittest.TestCase):
    def test_wildcards_anchors_specificity_and_group_selection(self):
        policy = Robots("""
          User-agent: *
          Disallow: /
          User-agent: landosaur-land-marketplace
          Disallow: /private*
          Allow: /private/public$
          User-agent: landosaur-land-marketplace
          Disallow: /sales?draft=*
          Crawl-delay: 2
          Request-rate: 1/3
        """)
        self.assertTrue(policy.allows(urlsplit("https://example.com/sales")))
        self.assertTrue(policy.allows(urlsplit("https://example.com/private/public")))
        self.assertFalse(policy.allows(urlsplit("https://example.com/private/public?x=1")))
        self.assertFalse(policy.allows(urlsplit("https://example.com/sales?draft=1")))
        self.assertEqual(policy.delay, 3)

    def test_encoded_paths_follow_the_same_rule(self):
        policy = Robots("User-agent: *\nDisallow: /caf%C3%A9\nDisallow: /a/b")
        self.assertFalse(policy.allows(urlsplit("https://example.com/café")))
        self.assertFalse(policy.allows(urlsplit("https://example.com/a/%62")))
        self.assertTrue(policy.allows(urlsplit("https://example.com/a%2Fb")))


class FetcherTest(unittest.TestCase):
    def test_content_redirect_checks_destination_robots_before_fetching(self):
        class FixtureFetcher(Fetcher):
            def __init__(self):
                super().__init__(pause=0, tries=1)
                self.visited = []

            def _request(self, url, origin, data, limit):
                self.visited.append(url)
                if url == "https://a.example/robots.txt":
                    return b"User-agent: *\nAllow: /"
                if url == "https://b.example/robots.txt":
                    return b"User-agent: *\nDisallow: /protected/"
                if url == "https://a.example/land":
                    headers = Message()
                    headers["Location"] = "https://b.example/protected/land"
                    raise HTTPError(url, 302, "redirect", headers, io.BytesIO())
                raise AssertionError("Unexpected fetch: " + url)

        fetcher = FixtureFetcher()
        with self.assertRaisesRegex(FetchError, "robots.txt disallows"):
            fetcher.text("https://a.example/land")
        self.assertEqual(fetcher.visited, ["https://a.example/robots.txt", "https://a.example/land",
                                           "https://b.example/robots.txt"])

    def test_forbidden_robot_file_fails_closed_and_missing_file_allows(self):
        class FixtureFetcher(Fetcher):
            def _request(self, url, origin, data, limit):
                if url.endswith("/robots.txt"):
                    code = 403 if origin == "https://blocked.example" else 404
                    raise HTTPError(url, code, "test", Message(), io.BytesIO())
                return b"row"

        fetcher = FixtureFetcher(tries=1)
        with self.assertRaisesRegex(FetchError, "robots.txt unreadable"):
            fetcher.text("https://blocked.example/land")
        self.assertEqual(fetcher.text("https://absent.example/land"), "row")


    def test_esri_absent_robots_route_has_explicit_response(self):
        class FixtureFetcher(Fetcher):
            def _request(self, url, origin, data, limit):
                if url.endswith("/robots.txt"):
                    reason = b"Invalid URL" if "services2." in origin else b"Forbidden"
                    raise HTTPError(url, 403, "test", Message(), io.BytesIO(reason))
                return b"records"

        fetcher = FixtureFetcher(tries=1)
        self.assertEqual(fetcher.text("https://services2.arcgis.com/arcgis/feature"), "records")
        with self.assertRaisesRegex(FetchError, "robots.txt unreadable"):
            fetcher.text("https://services3.arcgis.com/arcgis/feature")
