"""Bounded, read-only IGW transport for the standalone Cast adapter."""

from __future__ import annotations

import json
import math
import multiprocessing
import socket
import ssl
import errno
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

BASE_REPORT_KEYS = ("battery", "solar", "solar_today", "status", "alarms")
REPORT_KEYS = (*BASE_REPORT_KEYS, "flow")
FLOW_UNCONFIGURED = "Energy flow is not configured. Ask the gateway administrator to configure flow measurements."
METRICS = {
    "battery_soc": ("battery", "%", 0, 100),
    "solar_power": ("solar", "W", 0, 1e12),
    "solar_today": ("solar_today", "kWh", 0, 1e12),
    "load_power": ("flow", "W", 0, 1e12),
    "grid_power": ("flow", "W", -1e12, 1e12),
    "battery_power": ("flow", "W", -1e12, 1e12),
}
STATUSES = ("fresh", "stale", "unavailable", "unconfigured")
FALLBACK = "I cannot get a current energy report right now. Please try again."
MAX_BODY = 262144


class GatewayError(Exception):
    """A fixed error category safe to expose without transport details."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def optional_metric(value, key: str, *, report_status: str | None) -> dict | None:
    """Accept display values without copying source identifiers or inventing zeros."""
    if not isinstance(value, dict) or key not in METRICS:
        return None
    _, unit, minimum, maximum = METRICS[key]
    status, numeric, age = value.get("status"), value.get("value"), value.get("age_seconds")
    if (not isinstance(status, str) or status not in STATUSES or report_status is not None and status != report_status
        or value.get("unit") != unit):
        return None
    if status == "fresh":
        if (type(numeric) not in (int, float) or not minimum <= numeric <= maximum
            or not math.isfinite(numeric)):
            return None
    elif numeric is not None:
        return None
    clean = {"status": status, "value": numeric, "unit": unit}
    if type(age) is int and 0 <= age <= 2**64 - 1:
        clean["age_seconds"] = age
    return clean


def _valid_text(text):
    return (isinstance(text, str) and 0 < len(text.strip()) <= 1200
            and not any(ord(char) < 32 and char not in "\n\t\r" for char in text))


def validate_snapshot(body: object, *, now: float, max_age: int = 30) -> dict:
    """Preserve central warning text and reject contradictory or old envelopes."""
    if not isinstance(body, dict):
        raise GatewayError("invalid_response")
    generated = body.get("generated_at")
    metrics, reports = body.get("metrics"), body.get("reports")
    if (
        type(body.get("schema_version")) is not int or body["schema_version"] != 1
        or type(body.get("mqtt_connected")) is not bool
        or type(generated) not in (int, float)
        or not -1e12 < generated < 1e12 or not math.isfinite(generated)
        or not -5 <= now - generated <= max_age
        or not isinstance(metrics, dict)
        or not all(key in metrics for key in ("battery_soc", "solar_power", "solar_today"))
        or not isinstance(reports, dict)
    ):
        raise GatewayError("invalid_response")
    clean = {}
    for key in REPORT_KEYS:
        report = reports.get(key)
        if key == "flow" and key not in reports:
            clean[key] = {"text": FLOW_UNCONFIGURED, "status": "unconfigured"}
            continue
        if not isinstance(report, dict):
            raise GatewayError("invalid_response")
        status, text = report.get("status"), report.get("text")
        if (
            not isinstance(status, str) or status not in STATUSES or not _valid_text(text)
            or status == "fresh" and not body["mqtt_connected"]
        ):
            raise GatewayError("invalid_response")
        clean[key] = {"text": text.strip(), "status": status}
        brief = report.get("brief_text")
        if key == "status" and _valid_text(brief):
            clean[key]["brief_text"] = brief.strip()
    for metric_key, (report_key, _, _, _) in METRICS.items():
        if report_key == "flow" and "flow" not in reports:
            continue
        metric = optional_metric(metrics.get(metric_key), metric_key,
                                 report_status=None if report_key == "flow" else clean[report_key]["status"])
        if metric is not None and metric["status"] == "fresh" and not body["mqtt_connected"]:
            metric = None
        if metric is not None:
            clean[report_key].setdefault("metrics", {})[metric_key] = metric
    return {"generated_at": generated, "reports": clean}


def _transient_transport(error) -> bool:
    reason = error.reason if isinstance(error, URLError) else error
    # TLS verification and permanent DNS/address failures are never retried.
    return (isinstance(reason, (TimeoutError, ConnectionResetError, ConnectionAbortedError))
            or isinstance(reason, socket.gaierror) and reason.errno == socket.EAI_AGAIN
            or isinstance(reason, OSError) and not isinstance(reason, ssl.SSLError)
            and reason.errno in {errno.ECONNRESET, errno.ECONNABORTED, errno.ETIMEDOUT})


def fetch_snapshot(config, *, opener=None, now=time.time, clock=time.monotonic,
                   deadline_seconds=12) -> dict:
    """Retry one classified transient GET within the original deadline; never cache."""
    headers = {
        "Authorization": "Bearer " + config.igw_token,
        "Accept": "application/json", "Cache-Control": "no-cache, no-store",
        "User-Agent": "IGWCast/1.0",
    }
    if config.cf_client_id:
        headers["CF-Access-Client-Id"] = config.cf_client_id
        headers["CF-Access-Client-Secret"] = config.cf_client_secret
    request = Request(config.igw_url, headers=headers)
    transport = opener or build_opener(ProxyHandler({}), NoRedirects())
    deadline = clock() + deadline_seconds
    for attempt in range(2):
        remaining = deadline - clock()
        if remaining <= 0:
            raise GatewayError("transport_failure")
        try:
            with transport.open(request, timeout=min(5, remaining)) as response:
                if response.status != 200:
                    if response.status in {502, 503, 504} and attempt == 0:
                        continue
                    raise GatewayError("http_failure")
                if response.headers.get_content_type() != "application/json":
                    raise GatewayError("invalid_response")
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise GatewayError("invalid_response")
                return validate_snapshot(json.loads(raw), now=now(), max_age=config.max_age)
        except GatewayError:
            raise
        except HTTPError as exc:
            retry = exc.code in {502, 503, 504} and attempt == 0
            exc.close()
            if not retry:
                raise GatewayError("http_failure") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt != 0 or not _transient_transport(exc):
                raise GatewayError("transport_failure") from None
        except (ValueError, UnicodeError):
            raise GatewayError("invalid_response") from None
    raise GatewayError("transport_failure")


def _fetch_worker(connection, config):
    try:
        connection.send((True, fetch_snapshot(config)))
    except GatewayError as exc:
        connection.send((False, str(exc)))
    except Exception:
        connection.send((False, "invalid_response"))
    finally:
        connection.close()


def fetch_snapshot_bounded(config, *, deadline_seconds=12) -> dict:
    """Terminate even blocked DNS/slow-drip reads after a total wall-clock budget."""
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_fetch_worker, args=(writer, config), daemon=True)
    try:
        process.start()
        writer.close()
        if not reader.poll(deadline_seconds):
            raise GatewayError("transport_failure")
        try:
            success, value = reader.recv()
        except (EOFError, OSError):
            raise GatewayError("transport_failure") from None
        if not success:
            category = value if value in {"http_failure", "transport_failure", "invalid_response"} else "invalid_response"
            raise GatewayError(category)
        return value
    finally:
        reader.close()
        writer.close()
        if process.pid is not None:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            process.close()
