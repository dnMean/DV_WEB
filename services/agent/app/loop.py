"""Agent loop (spec 9.3): guard input -> LLM <-> tools via Gateway -> guard output."""
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser
from opspilot_common.errors import AppError

from app import guardrails, prompts
from app.config import Settings
from app.gateway_client import GatewayClient, GatewayError
from app.guardrails import GuardConfig
from app.llm import LLMClient, LLMError
from app.models import Conversation, Message
from app.tracing import Tracer

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    conversation_id: str
    answer: str
    status: str  # done | pending_approval | blocked | max_steps | budget_exceeded | error
    trace_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    ticket_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    llm_calls: int = 0


def get_owned_conversation(db: Session, conversation_id: str, user: CurrentUser) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise AppError(404, "conversation_not_found", "Không tìm thấy hội thoại")
    if not user.is_staff and conv.user_id != user.id:
        raise AppError(403, "forbidden", "Bạn không có quyền xem hội thoại này")
    return conv


def load_history(db: Session, conversation_id: str, limit: int) -> list[dict[str, Any]]:
    """Last `limit` messages of previous turns, compacted to what the conversation needs.

    Only user messages, final assistant answers and system notifications are kept: raw tool calls/results of
    old turns are dropped (they stay in the DB and traces), so the prompt does not grow with every tool result.
    """
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.kind != "blocked",
               Message.role.in_(("user", "assistant", "system")))
        .order_by(Message.id.desc())
        .limit(limit * 3)  # tool traffic is filtered below
    ).all()[::-1]
    rows = [m for m in rows if m.content and not m.tool_calls][-limit:]
    while rows and rows[0].role != "user":
        rows = rows[1:]
    return [m.to_llm() for m in rows]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class AgentRunner:
    def __init__(self, settings: Settings, llm: LLMClient, gateway: GatewayClient, guard: GuardConfig):
        self.s = settings
        self.llm = llm
        self.gateway = gateway
        self.guard = guard

    # -- persistence helpers ------------------------------------------------------------------

    def _save(self, db: Session, conv_id: str, msg: dict[str, Any], trace_id: str, kind: str = "normal") -> None:
        db.add(Message(
            conversation_id=conv_id, role=msg["role"], content=msg.get("content"),
            tool_calls=msg.get("tool_calls"), tool_call_id=msg.get("tool_call_id"), kind=kind, trace_id=trace_id,
        ))
        db.commit()

    # -- main entry ---------------------------------------------------------------------------

    def run(self, db: Session, user: CurrentUser, message: str, conversation_id: str | None = None) -> ChatResult:
        started = time.perf_counter()
        if conversation_id:
            conv = get_owned_conversation(db, conversation_id, user)
        else:
            conv = Conversation(user_id=user.id)
            db.add(conv)
            db.commit()

        history = load_history(db, conv.id, self.s.HISTORY_MAX_MESSAGES)
        tracer = Tracer(db, conv.id, user.id, self.guard.as_dict())
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        steps: list[dict[str, Any]] = []
        llm_calls = 0
        user_msg = {"role": "user", "content": message}

        def finish(status: str, answer: str, ticket_id: str | None = None, kind: str = "normal") -> ChatResult:
            self._save(db, conv.id, {"role": "assistant", "content": answer}, tracer.id, kind=kind)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            tracer.event("final", len(steps), {"status": status, "answer": answer, "ticket_id": ticket_id})
            tracer.finish(status, usage["prompt_tokens"], usage["completion_tokens"], latency_ms)
            logger.info("chat finished: conv=%s status=%s tools=%s", conv.id, status, [s["tool"] for s in steps])
            return ChatResult(conv.id, answer, status, tracer.id, steps, ticket_id, dict(usage), latency_ms, llm_calls)

        # 1. input guardrails
        for layer, enabled, check in (
            ("input_rules", self.guard.input_rules, lambda: guardrails.check_input_rules(message)),
            ("input_llm", self.guard.input_llm, lambda: guardrails.check_input_llm(message, self.llm)),
        ):
            if not enabled:
                continue
            g = check()
            usage["prompt_tokens"] += g.prompt_tokens
            usage["completion_tokens"] += g.completion_tokens
            tracer.event("guard", 0, {"layer": layer, "allowed": g.allowed, "reason": g.reason})
            if not g.allowed:
                self._save(db, conv.id, user_msg, tracer.id, kind="blocked")
                return finish("blocked", prompts.BLOCKED_ANSWER, kind="blocked")

        self._save(db, conv.id, user_msg, tracer.id)

        # 2. tools visible to this user's role
        try:
            tools = self.gateway.list_tools(user.token)
        except GatewayError as exc:
            tracer.event("tool_call", 0, {"error": "list_tools_failed", "message": str(exc)})
            return finish("error", prompts.TOOLS_ERROR_ANSWER)

        allowed_pii = (
            {guardrails.canonical_pii(v) for v in self.gateway.user_pii(user.token)} if self.guard.output_pii else set()
        )
        messages = [
            {"role": "system", "content": prompts.system_prompt(user.username, user.id, user.role)},
            *history,
            user_msg,
        ]
        call_counts: Counter[tuple[str, str]] = Counter()

        # 3. loop
        for step in range(1, self.s.AGENT_MAX_STEPS + 1):
            t0 = time.perf_counter()
            llm_calls += 1
            try:
                resp = self.llm.chat(messages, tools)
            except LLMError as exc:
                tracer.event("llm_call", step, {"error": exc.code, "message": exc.message},
                             latency_ms=round((time.perf_counter() - t0) * 1000, 1))
                return finish("error", prompts.LLM_ERROR_ANSWER)
            usage["prompt_tokens"] += resp.prompt_tokens
            usage["completion_tokens"] += resp.completion_tokens
            tracer.event(
                "llm_call", step,
                {"content": (resp.content or "")[:1000],
                 "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in resp.tool_calls]},
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
            )
            if not resp.tool_calls:  # a final answer is always delivered: its tokens are already spent
                answer = resp.content or ""
                if self.guard.output_pii:
                    g = guardrails.redact_pii(answer, allowed_pii)
                    tracer.event("guard", step, {"layer": "output_pii", "allowed": g.allowed,
                                                 "reason": g.reason, "redacted": len(g.flagged)})
                    answer = g.modified
                return finish("done", answer)

            # more steps needed: stop here if the budget is already used up
            if usage["prompt_tokens"] + usage["completion_tokens"] > self.s.AGENT_MAX_TOKENS:
                return finish("budget_exceeded", prompts.BUDGET_ANSWER)

            new_msgs: list[dict[str, Any]] = [resp.assistant_message()]
            pending: tuple[str, str, dict] | None = None  # (ticket_id, tool, arguments)
            for tc in resp.tool_calls:
                if pending:
                    obs = {"status": "error", "error": "skipped", "message": "Bỏ qua: đang chờ duyệt yêu cầu trước"}
                    new_msgs.append({"role": "tool", "tool_call_id": tc.id, "content": _canonical(obs)})
                    continue
                obs, arguments = self._execute(tc, user, conv.id, message, call_counts, tracer, step)
                steps.append({"step": step, "tool": tc.name, "arguments": arguments,
                              "status": obs.get("status"), "error": obs.get("error"),
                              "ticket_id": obs.get("ticket_id")})
                if obs.get("status") == "pending_approval":
                    pending = (obs["ticket_id"], tc.name, arguments)
                    content: Any = obs
                else:
                    if obs.get("status") == "ok" and self.guard.output_pii:
                        allowed_pii |= guardrails.collect_pii(obs.get("data"))
                    content = obs
                    if self.guard.tool_output:
                        g = guardrails.sanitize_tool_output(obs)
                        tracer.event("guard", step, {"layer": "tool_output", "tool": tc.name, "allowed": g.allowed,
                                                     "reason": g.reason, "flagged": g.flagged})
                        content = g.modified
                new_msgs.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(content, ensure_ascii=False, default=str)})

            for m in new_msgs:
                self._save(db, conv.id, m, tracer.id)
            messages.extend(new_msgs)
            if pending:
                ticket_id, tool, arguments = pending
                return finish("pending_approval", prompts.pending_answer(tool, arguments, ticket_id), ticket_id)

        return finish("max_steps", prompts.MAX_STEPS_ANSWER)

    def _execute(self, tc, user: CurrentUser, conv_id: str, user_message: str, call_counts: Counter,
                 tracer: Tracer, step: int) -> tuple[dict[str, Any], Any]:
        try:
            arguments = json.loads(tc.arguments or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
        except ValueError:
            return {"status": "error", "error": "invalid_json", "message": "Tham số tool không phải JSON object hợp lệ"}, tc.arguments

        key = (tc.name, _canonical(arguments))
        if call_counts[key] >= self.s.AGENT_MAX_SAME_CALL:
            obs = {"status": "error", "error": "duplicate_call",
                   "message": "Tool này đã được gọi với cùng tham số. Hãy dùng kết quả trước đó để trả lời."}
            tracer.event("tool_call", step, {"tool": tc.name, "arguments": arguments, "result": obs})
            return obs, arguments
        call_counts[key] += 1

        t0 = time.perf_counter()
        obs = self.gateway.invoke(user.token, tc.name, arguments, conv_id, user_message)
        tracer.event("tool_call", step, {"tool": tc.name, "arguments": arguments, "result": obs},
                     latency_ms=round((time.perf_counter() - t0) * 1000, 1))
        return obs, arguments
