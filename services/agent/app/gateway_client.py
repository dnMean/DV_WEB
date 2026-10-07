"""Agent -> Gateway / Auth calls. The agent never calls business services directly."""
import logging
from typing import Any

import httpx

from opspilot_common.logging import forward_headers

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(self, http: httpx.Client, gateway_url: str, auth_url: str, tool_timeout: float):
        self.http = http
        self.gateway_url = gateway_url.rstrip("/")
        self.auth_url = auth_url.rstrip("/")
        self.timeout = tool_timeout * 2 + 5  # gateway may retry once

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", **forward_headers()}

    def list_tools(self, token: str) -> list[dict[str, Any]]:
        try:
            resp = self.http.get(f"{self.gateway_url}/tools", headers=self._headers(token), timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayError(str(exc)) from exc

    def invoke(self, token: str, tool: str, arguments: dict[str, Any], conversation_id: str,
               user_message: str = "") -> dict[str, Any]:
        """Never raises: any failure becomes an error observation for the LLM."""
        try:
            resp = self.http.post(
                f"{self.gateway_url}/invoke", headers=self._headers(token), timeout=self.timeout,
                json={"tool": tool, "arguments": arguments, "conversation_id": conversation_id,
                      "user_message": user_message},
            )
            body = resp.json()
        except httpx.TimeoutException:
            return {"status": "error", "error": "timeout", "message": "Gateway không phản hồi"}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("gateway invoke failed: %s", exc)
            return {"status": "error", "error": "gateway_unavailable", "message": "Không gọi được Gateway"}
        if not isinstance(body, dict) or "status" not in body:
            body = body if isinstance(body, dict) else {}
            return {"status": "error", "error": body.get("error", "gateway_error"), "message": body.get("message", "")}
        return body

    def user_pii(self, token: str) -> set[str]:
        """Email/phone of the current user (allowed to appear in answers)."""
        try:
            resp = self.http.get(f"{self.auth_url}/auth/me", headers=self._headers(token), timeout=5.0)
            resp.raise_for_status()
            me = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("cannot load user profile for PII guard: %s", exc)
            return set()
        return {v for v in (me.get("email"), me.get("phone")) if v}
