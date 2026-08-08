from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
ALLOWED_CONTENT_TYPES = {"text/html", "text/plain"}


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    content: bytes
    filename: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored and data.strip():
            self.parts.append(data.strip())


class SafeWebFetcher:
    def __init__(self, max_bytes: int, timeout_seconds: float = 15.0) -> None:
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> FetchedPage:
        current = url
        for _ in range(4):
            self._validate_public_url(current)
            with httpx.stream("GET", current, follow_redirects=False, timeout=self._timeout_seconds) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect did not include a location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in ALLOWED_CONTENT_TYPES:
                    raise ValueError(f"Unsupported link content type: {content_type or 'unknown'}")
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > self._max_bytes:
                    raise ValueError("Linked page is too large")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise ValueError("Linked page is too large")
            content = bytes(body)
            if content_type == "text/html":
                parser = _TextExtractor()
                parser.feed(content.decode(response.encoding or "utf-8", errors="replace"))
                content = "\n".join(parser.parts).encode("utf-8")
            hostname = urlparse(current).hostname or "link"
            return FetchedPage(url=current, content=content, filename=f"{hostname}.txt")
        raise ValueError("Too many redirects")

    @staticmethod
    def _validate_public_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Only public HTTP(S) links are supported")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        for result in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(result[4][0])
            if not address.is_global:
                raise ValueError("Private or local links are not allowed")


def first_url(text: str) -> str | None:
    match = URL_PATTERN.search(text)
    return match.group(0).rstrip(".,);]") if match else None
