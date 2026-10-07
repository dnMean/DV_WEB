"""Helper to declare an endpoint as an agent tool via the `x-agent-tool` OpenAPI extension."""
from typing import Literal

Risk = Literal["low", "medium", "high"]


def agent_tool(name: str, risk: Risk, roles: list[str], dedup_fields: list[str] | None = None,
               precheck: str | None = None, confirm_args: list[str] | None = None) -> dict:
    """Use as `openapi_extra=agent_tool("get_order", "low", ["customer", "staff"])`.

    dedup_fields (high risk tools): arguments that identify "the same request" for approval
    de-duplication. Free-text fields such as `reason` should be left out, since the LLM may word
    them differently each time. Default: all arguments.
    precheck (high risk tools): path on the same service, called by the Gateway with the user's JWT and the
    same body before creating an approval ticket; a non-2xx answer rejects the request immediately.
    confirm_args: arguments whose value must appear literally in the end user's own chat message
    (checked by the Gateway), so the LLM cannot pick them from untrusted data by itself.
    """
    ext = {"name": name, "risk": risk, "roles": roles}
    if dedup_fields:
        ext["dedup_fields"] = dedup_fields
    if precheck:
        ext["precheck"] = precheck
    if confirm_args:
        ext["confirm_args"] = confirm_args
    return {"x-agent-tool": ext}
