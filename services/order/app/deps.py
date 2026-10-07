"""Synchronous internal calls to Product and Payment used while ordering (docs/USECASES.md section 3b)."""
import logging
from typing import Any

import httpx

from opspilot_common.auth import INTERNAL_SECRET_HEADER, get_auth_settings
from opspilot_common.errors import AppError
from opspilot_common.logging import forward_headers

from app.config import get_settings

logger = logging.getLogger(__name__)


class Dependencies:
    def __init__(self, http: httpx.Client):
        s = get_settings()
        self.http = http
        self.product_url = s.PRODUCT_URL.rstrip("/")
        self.payment_url = s.PAYMENT_URL.rstrip("/")
        self.timeout = s.DEPENDENCY_TIMEOUT_SECONDS

    def _call(self, method: str, url: str, **kw) -> httpx.Response:
        headers = {INTERNAL_SECRET_HEADER: get_auth_settings().INTERNAL_SECRET, **forward_headers(),
                   **kw.pop("headers", {})}
        try:
            return self.http.request(method, url, headers=headers, timeout=self.timeout, **kw)
        except httpx.HTTPError as exc:
            logger.error("%s %s failed: %s", method, url, exc)
            raise AppError(503, "dependency_unavailable", "Hệ thống kho/thanh toán tạm thời không phản hồi")

    @staticmethod
    def _business_error(resp: httpx.Response) -> AppError:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code in (404, 409, 422) and isinstance(body, dict) and "error" in body:
            extra = {k: v for k, v in body.items() if k not in ("error", "message")}
            return AppError(409 if resp.status_code == 409 else 422, body["error"], body.get("message", ""), extra)
        return AppError(503, "dependency_unavailable", "Hệ thống kho/thanh toán trả lỗi không mong đợi")

    def catalog(self, product_ids: list[int]) -> dict[int, dict[str, Any]]:
        resp = self._call("GET", f"{self.product_url}/internal/products",
                          params={"ids": ",".join(str(i) for i in product_ids)})
        if not resp.is_success:
            raise self._business_error(resp)
        return {p["id"]: p for p in resp.json()}

    def reserve(self, items: list[dict[str, int]], key: str, reason: str) -> None:
        """Take every item out of stock, or nothing (409 out_of_stock)."""
        resp = self._call("POST", f"{self.product_url}/internal/inventory/reserve",
                          json={"items": items, "reason": reason}, headers={"Idempotency-Key": key})
        if not resp.is_success:
            raise self._business_error(resp)

    def release(self, items: list[dict[str, int]], key: str, reason: str) -> None:
        """Best-effort undo of `reserve` when the order could not be saved."""
        try:
            self._call("POST", f"{self.product_url}/internal/inventory/restock",
                       json={"items": items, "reason": reason}, headers={"Idempotency-Key": key})
        except AppError:
            logger.error("could not release reservation %s: stock must be fixed by hand", key)

    def charge(self, order_id: int, user_id: int, amount: int, method: str) -> dict[str, Any]:
        resp = self._call("POST", f"{self.payment_url}/internal/payments",
                          json={"order_id": order_id, "user_id": user_id, "amount": amount, "method": method})
        if not resp.is_success:
            raise self._business_error(resp)
        return resp.json()
