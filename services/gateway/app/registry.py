"""Tool registry built from the `x-agent-tool` extension in each service's OpenAPI document."""
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
_RISKS = {"low", "medium", "high"}


class RegistryError(Exception):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    risk: str
    roles: list[str]
    method: str
    service_url: str
    path: str
    parameters: dict[str, Any]
    # argument name -> "path" | "query" | "body"
    locations: dict[str, str] = field(default_factory=dict)
    # arguments that identify a duplicate approval request (None = all)
    dedup_fields: list[str] | None = None
    # path on the same service validating a high risk call before a ticket is created
    precheck: str | None = None
    # arguments that must appear literally in the user's own message (e.g. ticket_id for approve_ticket)
    confirm_args: list[str] | None = None

    @property
    def is_write(self) -> bool:
        return self.method != "GET"

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def meta(self) -> dict[str, Any]:
        return asdict(self)


def _resolve(node: Any, components: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    """Inline $ref, drop titles, collapse Optional (anyOf [X, null]) to X."""
    if isinstance(node, list):
        return [_resolve(x, components, seen) for x in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            return {}
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        return _resolve({**components.get(name, {}), **siblings}, components, seen + (name,))
    out = {k: _resolve(v, components, seen) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    if "anyOf" in out:
        options = [o for o in out["anyOf"] if o.get("type") != "null"]
        if len(options) == 1 and len(options) < len(out["anyOf"]):
            rest = {k: v for k, v in out.items() if k != "anyOf"}
            out = {**options[0], **rest}
    if out.get("default", "_") is None:
        del out["default"]
    return out


def build_tools(service_url: str, openapi: dict[str, Any]) -> list[ToolSpec]:
    components = openapi.get("components", {}).get("schemas", {})
    tools = []
    for path, item in openapi.get("paths", {}).items():
        for method, op in item.items():
            if method not in _HTTP_METHODS or "x-agent-tool" not in op:
                continue
            ext = op["x-agent-tool"]
            name = ext.get("name")
            if not name or ext.get("risk") not in _RISKS or not isinstance(ext.get("roles"), list):
                raise RegistryError(f"invalid x-agent-tool on {method.upper()} {path} of {service_url}")

            properties: dict[str, Any] = {}
            required: list[str] = []
            locations: dict[str, str] = {}

            def add(arg: str, schema: dict, location: str, is_required: bool) -> None:
                if arg in properties:
                    raise RegistryError(f"tool {name}: argument '{arg}' defined twice")
                properties[arg] = schema
                locations[arg] = location
                if is_required:
                    required.append(arg)

            for param in item.get("parameters", []) + op.get("parameters", []):
                param = _resolve(param, components)
                if param.get("in") not in ("path", "query"):
                    continue  # headers (Idempotency-Key, ...) are set by the gateway, not the LLM
                schema = param.get("schema", {})
                if param.get("description") and "description" not in schema:
                    schema["description"] = param["description"]
                add(param["name"], schema, param["in"], param["in"] == "path" or param.get("required", False))

            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body:
                body = _resolve(body, components)
                for arg, schema in body.get("properties", {}).items():
                    add(arg, schema, "body", arg in body.get("required", []))

            description = ". ".join(
                s.strip().rstrip(".") for s in (op.get("summary"), op.get("description")) if s
            ) + "."
            tools.append(ToolSpec(
                name=name, description=description, risk=ext["risk"], roles=list(ext["roles"]),
                method=method.upper(), service_url=service_url, path=path,
                parameters={
                    "type": "object", "properties": properties, "required": required,
                    "additionalProperties": False,
                },
                locations=locations,
                dedup_fields=ext.get("dedup_fields"),
                precheck=ext.get("precheck"),
                confirm_args=ext.get("confirm_args"),
            ))
    return tools


def merge(by_service: dict[str, list[ToolSpec]]) -> dict[str, ToolSpec]:
    tools: dict[str, ToolSpec] = {}
    for url, specs in by_service.items():
        for spec in specs:
            if spec.name in tools:
                raise RegistryError(
                    f"duplicate tool name '{spec.name}' in {url} and {tools[spec.name].service_url}"
                )
            tools[spec.name] = spec
    return tools


class Registry:
    def __init__(self) -> None:
        self._by_service: dict[str, list[ToolSpec]] = {}
        self._tools: dict[str, ToolSpec] = {}

    async def refresh(self, client: httpx.AsyncClient, service_urls: list[str], *, strict: bool) -> None:
        """Reload every service's OpenAPI. Unreachable services keep their previous tools.

        Duplicate tool names raise when `strict` (startup); otherwise the old registry is kept.
        """
        by_service = dict(self._by_service)
        for url in service_urls:
            try:
                resp = await client.get(f"{url}/openapi.json", timeout=5.0)
                resp.raise_for_status()
                by_service[url] = build_tools(url, resp.json())
            except RegistryError:
                if strict:
                    raise
                logger.exception("invalid tool definitions from %s; keeping previous", url)
            except Exception as exc:
                logger.warning("cannot load OpenAPI from %s: %s", url, exc)
        try:
            tools = merge(by_service)
        except RegistryError:
            if strict:
                raise
            logger.exception("registry refresh rejected; keeping previous registry")
            return
        self._by_service, self._tools = by_service, tools
        logger.info("registry loaded %s tools from %s services", len(tools), len(by_service))

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def for_role(self, role: str) -> list[ToolSpec]:
        return [t for t in self.all() if role in t.roles]
