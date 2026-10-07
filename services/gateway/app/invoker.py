"""Argument handling and service calls for `POST /invoke` (spec 7.3)."""
import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx
from jsonschema import Draft202012Validator

from app.registry import ToolSpec

logger = logging.getLogger(__name__)

_INT_RE = re.compile(r"^-?\d+$")
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def idempotency_key(user_id: int, tool: str, arguments: dict, conversation_id: str) -> str:
    raw = f"{user_id}|{tool}|{canonical_json(arguments)}|{conversation_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def coerce_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
    """LLMs often send numbers as strings ("1002"); convert those for integer/number params."""
    props = spec.parameters.get("properties", {})
    out = dict(arguments)
    for name, value in arguments.items():
        if not isinstance(value, str):
            continue
        typ = props.get(name, {}).get("type")
        if typ == "integer" and _INT_RE.match(value.strip()):
            out[name] = int(value.strip())
        elif typ == "number" and _NUM_RE.match(value.strip()):
            out[name] = float(value.strip())
    return out


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> str | None:
    """Short, LLM-readable error message, or None when valid."""
    errors = sorted(Draft202012Validator(spec.parameters).iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return None
    parts = []
    for err in errors[:3]:
        where = ".".join(str(p) for p in err.path)
        parts.append(f"{where}: {err.message}" if where else err.message)
    return "; ".join(parts)


def build_request(spec: ToolSpec, arguments: dict[str, Any]) -> tuple[str, dict, dict | None]:
    path_args = {k: quote(str(v), safe="") for k, v in arguments.items() if spec.locations.get(k) == "path"}
    query = {k: v for k, v in arguments.items() if spec.locations.get(k) == "query"}
    body = {k: v for k, v in arguments.items() if spec.locations.get(k) == "body"}
    url = spec.service_url + spec.path.format(**path_args)
    has_body = any(loc == "body" for loc in spec.locations.values())
    return url, query, (body if has_body else None)


def error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": "error", "error": code, "message": message, **extra}


def truncate(data: Any, max_chars: int) -> tuple[Any, bool]:
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return data, False
    return text[:max_chars], True


def normalize_response(resp: httpx.Response, max_chars: int) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        payload = resp.text
    if resp.is_success:
        data, truncated = truncate(payload, max_chars)
        result = {"status": "ok", "data": data}
        if truncated:
            result["truncated"] = True
        return result
    if isinstance(payload, dict) and "error" in payload:
        extra = {k: v for k, v in payload.items() if k not in ("error", "message")}
        return error(payload["error"], str(payload.get("message", "")), http_status=resp.status_code, **extra)
    return error("service_error", str(payload)[:300], http_status=resp.status_code)


async def precheck(client: httpx.AsyncClient, spec: ToolSpec, arguments: dict[str, Any],
                   headers: dict[str, str], *, timeout: float) -> dict[str, Any] | None:
    """Ask the service whether a high risk call would be accepted. None = OK, else an error result."""
    _, query, body = build_request(spec, arguments)
    try:
        resp = await client.post(spec.service_url + spec.precheck, params=query, json=body, headers=headers,
                                 timeout=timeout)
    except httpx.HTTPError as exc:
        return error("service_unavailable", f"Không kiểm tra được yêu cầu: {type(exc).__name__}")
    return None if resp.is_success else normalize_response(resp, 4000)


async def call_service(
    client: httpx.AsyncClient,
    spec: ToolSpec,
    arguments: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout: float,
    max_chars: int,
) -> dict[str, Any]:
    """Execute the tool's HTTP call. Read tools are retried once on network errors / 5xx."""
    url, query, body = build_request(spec, arguments)
    attempts = 1 if spec.is_write else 2
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.request(spec.method, url, params=query, json=body, headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            if attempt < attempts:
                continue
            return error("timeout", f"Service không phản hồi trong {timeout:g}s")
        except httpx.HTTPError as exc:
            if attempt < attempts:
                continue
            return error("service_unavailable", f"Không kết nối được service: {type(exc).__name__}")
        if resp.status_code >= 500 and attempt < attempts:
            logger.warning("%s returned %s, retrying", spec.name, resp.status_code)
            continue
        return normalize_response(resp, max_chars)
    raise AssertionError("unreachable")
