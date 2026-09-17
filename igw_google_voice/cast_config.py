"""Deployment-only configuration; API callers cannot select targets or URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import os
from urllib.parse import urlsplit
from uuid import UUID

from .__main__ import local_http_host, validate_url


@dataclass(frozen=True)
class CastConfig:
    igw_url: str = field(repr=False)
    igw_token: str = field(repr=False)
    api_token: str = field(repr=False)
    cast_host: str = field(repr=False)
    cast_uuid: UUID = field(repr=False)
    media_base_url: str = field(repr=False)
    bind_host: str = field(default="0.0.0.0", repr=False)
    port: int = 8091
    max_age: int = 30
    cf_client_id: str = field(default="", repr=False)
    cf_client_secret: str = field(default="", repr=False)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        def required(key):
            value = env.get(key, "")
            if not value or any(char.isspace() for char in value):
                raise ValueError("Missing or invalid service configuration.")
            return value
        try:
            url = validate_url(required("IGW_URL"), env.get("IGW_ALLOW_LOCAL_HTTP") == "true")
            token, api_token = required("IGW_READ_TOKEN"), required("CAST_API_TOKEN")
            if len(token) < 16 or len(api_token) < 32:
                raise ValueError()
            host = str(ipaddress.ip_address(required("CAST_HOST")))
            if not local_http_host(host) or ipaddress.ip_address(host).is_loopback:
                raise ValueError()
            media_url = required("CAST_MEDIA_BASE_URL").rstrip("/")
            parsed = urlsplit(media_url)
            # The media server is deliberately a private LAN endpoint, never a public tunnel.
            if (parsed.scheme != "http" or not parsed.hostname
                or not local_http_host(parsed.hostname)
                or ipaddress.ip_address(parsed.hostname).is_loopback
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path):
                raise ValueError()
            port = int(env.get("CAST_PORT", "8091"))
            if not 1024 <= port <= 65535 or (parsed.port or 80) != port:
                raise ValueError()
            bind = str(ipaddress.ip_address(env.get("CAST_BIND_HOST", parsed.hostname)))
            if ":" in bind:  # HTTPServer uses AF_INET; reject unsupported configuration.
                raise ValueError()
            age = int(env.get("IGW_MAX_RESPONSE_AGE", "30"))
            if not 5 <= age <= 300:
                raise ValueError()
            client_id = env.get("CF_ACCESS_CLIENT_ID", "")
            client_secret = env.get("CF_ACCESS_CLIENT_SECRET", "")
            if bool(client_id) != bool(client_secret) or (client_id and not url.startswith("https://")):
                raise ValueError()
            if any(c.isspace() for c in client_id + client_secret):
                raise ValueError()
            return cls(url, token, api_token, host, UUID(required("CAST_UUID")), media_url,
                       bind, port, age, client_id, client_secret)
        except (ValueError, TypeError):
            raise ValueError("Missing or invalid service configuration; see the standalone Cast guide.") from None
