"""Multi-agent mode: a router picks one specialist agent, each specialist only sees the tools of its domain.

    tin nhắn ──► GuardAgent (input) ──► RouterAgent ──► OrderAgent | SalesAgent | RefundAgent | GeneralAgent
                                                          │  ▲
                                                          └──┘ transfer_to_agent (handoff, tối đa AGENT_MAX_HANDOFFS)

Why: least privilege (OWASP LLM06 Excessive Agency). A specialist cannot even propose a write tool of another domain
(the Sales agent never sees refund_payment), and each prompt only carries the rules of its own tools. The Gateway
still enforces roles, schemas, confirmation and approval: the split narrows what the LLM is offered, it is not the
security boundary.
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app import prompts
from app.guardrails import normalize
from app.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

HANDOFF_TOOL = "transfer_to_agent"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    scope: str  # one line: what this agent handles (shown to the router and to the other agents)
    tools: frozenset[str] | None  # None = every tool the user's role may use (single-agent mode)
    rules: tuple[str, ...] = ()  # rule ids of prompts.RULES, or full rule texts

    def select_tools(self, available: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.tools is None:
            return list(available)
        return [t for t in available if t["function"]["name"] in self.tools]

    def owns(self, tool: str) -> bool:
        return self.tools is None or tool in self.tools

    def system_prompt(self, username: str, user_id: int, role: str) -> str:
        if self.tools is None:
            return prompts.system_prompt(username, user_id, role)
        rules = [prompts.RULES.get(r, r) for r in self.rules]
        return prompts.specialist_prompt(self.title, self.scope, rules, directory(exclude=self.name),
                                         username, user_id, role)


SINGLE = AgentSpec("single", "Trợ lý CSKH", "mọi yêu cầu", tools=None)

# Read tools that several domains need (looking up the order being discussed) are shared; every WRITE tool
# belongs to exactly one agent.
SPECIALISTS: dict[str, AgentSpec] = {a.name: a for a in (
    AgentSpec(
        "order", "Agent Đơn hàng & Vận chuyển",
        "tra cứu/liệt kê đơn hàng, trạng thái giao hàng, huỷ đơn chưa thanh toán, đổi địa chỉ giao; "
        "staff: tìm đơn, cập nhật trạng thái vận chuyển",
        frozenset({"list_my_orders", "search_orders", "get_order", "cancel_order", "get_shipment",
                   "update_shipping_address", "update_shipment_status", "get_payment"}),
        ("1", "2", "2b", "3a", "3", "4", "5", prompts.RULE_7_ORDER, "8", "9"),
    ),
    AgentSpec(
        "sales", "Agent Sản phẩm & Đặt hàng",
        "hỏi sản phẩm, giá, tồn kho; báo giá, đặt hàng (xác nhận bằng mã báo giá), thanh toán đơn mới",
        frozenset({"search_products", "get_product", "check_stock", "quote_order", "place_order", "pay_order",
                   "get_order"}),
        ("1", "2b", "3a", "3", "4", "5", "6b", "8", "9"),
    ),
    AgentSpec(
        "refund", "Agent Thanh toán & Hoàn tiền",
        "thông tin thanh toán, khả năng hoàn tiền, tạo yêu cầu hoàn tiền, trạng thái yêu cầu; "
        "staff: xem, đồng ý, từ chối yêu cầu hoàn tiền",
        frozenset({"get_payment", "check_refund_eligibility", "refund_payment", "get_approval_ticket",
                   "list_refund_requests", "approve_refund", "reject_refund", "get_order"}),
        ("1", "2", "2b", "3a", "3", "4", "5", "6", prompts.RULE_7_REFUND, "8", "9"),
    ),
    AgentSpec(
        "general", "Agent Tiếp nhận",
        "lời chào, câu hỏi chung về cách dùng trợ lý, câu không liên quan đến cửa hàng; không có công cụ dữ liệu",
        frozenset(),
        ("1", "2b", "4", "8", "9"),
    ),
)}
DEFAULT_SPECIALIST = "general"


def directory(exclude: str | None = None) -> str:
    return "\n".join(f"- {a.name}: {a.title} — {a.scope}" for a in SPECIALISTS.values() if a.name != exclude)


def unassigned_tools(available: list[dict[str, Any]]) -> list[str]:
    """Tools the Gateway offers that no specialist owns (a new tool must be assigned to an agent above)."""
    owned = set().union(*(a.tools for a in SPECIALISTS.values() if a.tools is not None))
    return [t["function"]["name"] for t in available if t["function"]["name"] not in owned]


def handoff_tool(current: str) -> dict[str, Any]:
    targets = [n for n in SPECIALISTS if n != current]
    return {"type": "function", "function": {
        "name": HANDOFF_TOOL,
        "description": "Chuyển yêu cầu sang agent chuyên trách khác khi yêu cầu (hoặc một phần) nằm ngoài phạm vi "
                       "công cụ của bạn. Agent mới nhận toàn bộ hội thoại của lượt này.",
        "parameters": {"type": "object", "properties": {
            "agent": {"type": "string", "enum": targets, "description": "agent nhận việc"},
            "reason": {"type": "string", "description": "lý do ngắn"},
        }, "required": ["agent", "reason"], "additionalProperties": False},
    }}


# --- router ---------------------------------------------------------------------------------------

@dataclass
class Route:
    agent: str
    reason: str
    method: str  # llm | keywords (fallback when the router LLM fails or answers something invalid)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_called: bool = False


# Fallback only: used when the router LLM is unavailable or returns an unknown agent. Order matters.
_KEYWORDS = [
    ("refund", r"\b(hoan tien|hoan lai|refund|tra lai tien|yeu cau hoan|duyet|tu choi|thanh toan bao nhieu)\b"),
    ("sales", r"\b(mua|dat hang|bao gia|xac nhan [a-z0-9]{6}|san pham|con hang|gia bao nhieu|tai nghe|sac|cap|"
              r"dien thoai|thanh toan don)\b"),
    ("order", r"\b(don|giao|van chuyen|dia chi|huy|lay hang)\b"),
]


def route_by_keywords(message: str) -> str:
    text = normalize(message)
    for agent, pattern in _KEYWORDS:
        if re.search(pattern, text):
            return agent
    return DEFAULT_SPECIALIST


def route(llm: LLMClient, message: str, history: list[dict[str, Any]], role: str) -> Route:
    """One LLM call without tools that answers {"agent": ..., "reason": ...}."""
    context = [m for m in history if m["role"] in ("user", "assistant") and m.get("content")][-4:]
    lines = [f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {m['content'][:300]}" for m in context]
    user_content = ("Các lượt trước:\n" + "\n".join(lines) + "\n\n" if lines else "") + f"Tin nhắn mới nhất:\n{message}"
    try:
        resp = llm.chat([
            {"role": "system", "content": prompts.ROUTER_PROMPT.format(role=role, directory=directory())},
            {"role": "user", "content": user_content},
        ])
    except LLMError as exc:
        logger.warning("router unavailable (%s), routing by keywords", exc.code)
        return Route(route_by_keywords(message), f"router lỗi ({exc.code})", "keywords", llm_called=True)
    tokens = {"prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens, "llm_called": True}
    match = re.search(r"\{.*\}", resp.content or "", re.S)
    try:
        verdict = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        verdict = {}
    agent = str(verdict.get("agent", "")).strip().lower()
    if agent in SPECIALISTS:
        return Route(agent, str(verdict.get("reason", ""))[:200], "llm", **tokens)
    return Route(route_by_keywords(message), f"router trả về không hợp lệ: {(resp.content or '')[:80]!r}",
                 "keywords", **tokens)
