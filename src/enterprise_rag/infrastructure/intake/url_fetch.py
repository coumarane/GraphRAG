"""Safe remote URL download with SSRF protections."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Sequence
from urllib.parse import ParseResult, urlparse

import httpx

from enterprise_rag.domain.storage.mime import assert_within_size_limit
from enterprise_rag.domain.storage.object_keys import sanitize_filename
from enterprise_rag.domain.storage.protocols import SourceBytes
from enterprise_rag.infrastructure.intake.mime_detection import detect_mime_type
from enterprise_rag.shared.exceptions import TransientError, ValidationError

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class SafeUrlFetcher:
    """Download remote documents with DNS revalidation and private-IP blocking."""

    def __init__(
        self,
        *,
        max_upload_bytes: int,
        timeout_seconds: float = 30.0,
        max_redirects: int = 3,
        allowed_schemes: Sequence[str] = ("https",),
    ) -> None:
        self._max_upload_bytes = max_upload_bytes
        self._timeout_seconds = timeout_seconds
        self._max_redirects = max_redirects
        self._allowed_schemes = tuple(scheme.lower() for scheme in allowed_schemes)

    async def fetch(self, url: str) -> SourceBytes:
        parsed = self._validate_url(url)
        hostname = parsed.hostname
        if hostname is None:
            raise ValidationError("URL host is required", details={"url": url})

        await self._assert_host_safe(hostname)

        timeout = httpx.Timeout(self._timeout_seconds)
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=0)
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            current = url
            for redirect_count in range(self._max_redirects + 1):
                parsed_current = self._validate_url(current)
                host = parsed_current.hostname
                if host is None:
                    raise ValidationError("Redirect URL host is required")
                await self._assert_host_safe(host)

                try:
                    response = await client.get(current)
                except httpx.TimeoutException as exc:
                    raise TransientError(
                        "Remote URL download timed out",
                        details={"url": self._redact_url(current)},
                        cause=exc,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise TransientError(
                        "Remote URL download failed",
                        details={"url": self._redact_url(current)},
                        cause=exc,
                    ) from exc

                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValidationError("Redirect response missing Location header")
                    current = str(httpx.URL(current).join(location))
                    if redirect_count >= self._max_redirects:
                        raise ValidationError(
                            "Too many redirects while downloading remote URL",
                            details={"max_redirects": self._max_redirects},
                        )
                    continue

                if response.status_code >= 400:
                    raise ValidationError(
                        "Remote URL returned an error status",
                        details={
                            "status_code": response.status_code,
                            "url": self._redact_url(current),
                        },
                    )

                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError as exc:
                        raise ValidationError("Invalid Content-Length header") from exc
                    assert_within_size_limit(declared, max_upload_bytes=self._max_upload_bytes)

                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > self._max_upload_bytes:
                        raise ValidationError(
                            "Remote download exceeded maximum upload size",
                            details={"max_upload_bytes": self._max_upload_bytes},
                        )

                payload = bytes(data)
                assert_within_size_limit(len(payload), max_upload_bytes=self._max_upload_bytes)
                filename = self._filename_from_url(parsed_current.path) or "download.bin"
                mime_type = detect_mime_type(payload, filename=filename)
                return SourceBytes(
                    filename=filename,
                    mime_type=mime_type,
                    content=payload,
                    source_uri=self._redact_url(url),
                )

        raise ValidationError("Remote URL download exhausted redirects without content")

    def _validate_url(self, url: str) -> ParseResult:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in self._allowed_schemes:
            raise ValidationError(
                "URL scheme is not allowed",
                details={"scheme": scheme, "allowed_schemes": list(self._allowed_schemes)},
            )
        if parsed.username or parsed.password:
            raise ValidationError("Credential-bearing URLs are not allowed")
        if not parsed.hostname:
            raise ValidationError("URL host is required")
        if parsed.port in {0}:
            raise ValidationError("Invalid URL port")
        return parsed

    async def _assert_host_safe(self, hostname: str) -> None:
        lowered = hostname.lower().rstrip(".")
        if lowered in {"localhost", "metadata.google.internal"}:
            raise ValidationError(
                "URL host is blocked",
                details={"hostname": hostname},
            )
        try:
            ipaddress.ip_address(lowered)
        except ValueError:
            pass
        else:
            self._assert_ip_safe(lowered)
            return

        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                hostname,
                None,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ValidationError(
                "Unable to resolve remote URL host",
                details={"hostname": hostname},
                cause=exc,
            ) from exc

        if not infos:
            raise ValidationError(
                "DNS resolution returned no addresses", details={"hostname": hostname}
            )
        for info in infos:
            address = info[4][0]
            self._assert_ip_safe(address)

    def _assert_ip_safe(self, address: str) -> None:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValidationError(
                "Invalid IP address from DNS", details={"address": address}
            ) from exc
        if any(ip in network for network in _BLOCKED_NETWORKS):
            raise ValidationError(
                "URL resolves to a blocked address range",
                details={"address": address},
            )
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValidationError(
                "URL resolves to a non-public address",
                details={"address": address},
            )

    @staticmethod
    def _filename_from_url(path: str) -> str | None:
        candidate = path.rsplit("/", 1)[-1]
        if not candidate:
            return None
        try:
            return sanitize_filename(candidate)
        except ValidationError:
            return "download.bin"

    @staticmethod
    def _redact_url(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path or ""
        return f"{parsed.scheme}://{host}{path}"
