"""Guardrail layers (spec 9.5). Each returns a GuardResult and can be toggled independently."""
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import Settings
from app.llm import LLMClient, LLMError
from app.prompts import INJECTION_CLASSIFIER_PROMPT

logger = logging.getLogger(__name__)

HIDDEN_TEXT = "[nội dung bị ẩn: nghi ngờ chỉ dẫn độc hại]"
REDACTED = "[đã ẩn]"


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    modified: Any = None
    flagged: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class GuardConfig:
    input_rules: bool = True
    input_llm: bool = False
    tool_output: bool = True
    output_pii: bool = True

    @classmethod
    def from_settings(cls, s: Settings) -> "GuardConfig":
        return cls(s.GUARD_INPUT_RULES, s.GUARD_INPUT_LLM, s.GUARD_TOOL_OUTPUT, s.GUARD_OUTPUT_PII)

    def override(self, values: dict[str, Any]) -> "GuardConfig":
        merged = asdict(self)
        merged.update({k: bool(v) for k, v in values.items() if k in merged})
        return GuardConfig(**merged)

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


def normalize(text: str) -> str:
    """Lowercase, strip Vietnamese diacritics, collapse whitespace."""
    text = text.lower().replace("đ", "d")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


# Patterns run on normalize()d text (no accents, lowercase).
_INJECTION_PATTERNS = [
    # English
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|all|your|the|any)\b.{0,20}\b(instructions?|prompts?|rules|guidelines|directions)\b",
    r"\b(system|developer|hidden|initial|original)\s+(prompt|instructions?|message)\b",
    r"\b(reveal|show|print|repeat|display|output)\b.{0,30}\b(your|the)\b.{0,15}\b(prompt|instructions?|rules)\b",
    r"\byou\s+are\s+now\b",
    r"\bpretend\s+(to\s+be|you\s+are|that)\b",
    r"\bact\s+as\s+(an?\s+)?(admin|administrator|developer|system|root|unrestricted)\b",
    r"\b(jailbreak|do\s+anything\s+now|developer\s+mode)\b",
    # Vietnamese (accents stripped)
    r"\b(bo qua|phot lo|lo di|quen|khong can tuan theo|vo hieu hoa)\b( het| tat ca| moi| cac| nhung| toan bo)*\s+(huong dan|chi dan|chi thi|quy tac|luat|rang buoc)\b",
    r"\b(loi nhac|prompt|chi dan|huong dan|chi thi)\s+(he thong|goc|an|ban dau)\b",
    r"\bban\s+(bay gio\s+|gio\s+|tu nay\s+)?(la|se la|dong vai|hay dong vai)\b.{0,25}\b(admin|quan tri vien|nha phat trien|developer|he thong|khong (co )?gioi han|dan|hacker)\b",
    r"\b(tu gio|tu bay gio|tu nay)\b.{0,10}\bban la\b",
    r"\bdong vai\b.{0,30}\b(admin|quan tri|nha phat trien|developer|khong (co )?gioi han|hacker|he thong)\b",
    r"\bche do\s+(nha phat trien|developer|khong gioi han|god|admin)\b",
    r"\bgia vo\b.{0,20}\b(la|ban la|rang)\b",
    r"(^|\n)\s*(system|he thong|admin)\s*:",
]
# Extra patterns that only make sense in tool output (data should never tell the agent what to do).
_TOOL_DIRECTIVE_PATTERNS = [
    r"\b(goi|call|invoke|thuc hien|execute|run|su dung|dung)\s+(tool\s+|ham\s+|cong cu\s+)?[a-z]+_[a-z_]+\b",
    r"\b(refund_payment|cancel_order|update_shipping_address)\b",
    r"\b(assistant|chatbot|tro ly ao|tro ly ai)\b.{0,20}\b(phai|must|should|hay)\b",
]
_INJECTION_RE = [re.compile(p) for p in _INJECTION_PATTERNS]
_TOOL_RE = _INJECTION_RE + [re.compile(p) for p in _TOOL_DIRECTIVE_PATTERNS]
_DAN_RE = re.compile(r"\bDAN\b")  # case-sensitive on the raw text ("dân" normalizes to "dan")


def _match(text: str, patterns: list[re.Pattern]) -> str | None:
    norm = normalize(text)
    for pat in patterns:
        m = pat.search(norm)
        if m:
            return m.group(0)
    if _DAN_RE.search(text):
        return "DAN"
    return None


def check_input_rules(message: str) -> GuardResult:
    hit = _match(message, _INJECTION_RE)
    if hit:
        return GuardResult(False, f"input khớp mẫu injection: '{hit}'", flagged=[hit])
    return GuardResult(True, "", modified=message)


def check_input_llm(message: str, llm: LLMClient) -> GuardResult:
    """LLM classifier. Fails open (allowed) if the classifier itself errors."""
    try:
        resp = llm.chat([
            {"role": "system", "content": INJECTION_CLASSIFIER_PROMPT},
            {"role": "user", "content": message},
        ])
    except LLMError as exc:
        logger.warning("input classifier unavailable: %s", exc.message)
        return GuardResult(True, f"classifier lỗi ({exc.code}), cho qua")
    raw = (resp.content or "").strip()
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        verdict = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        verdict = {}
    tokens = {"prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens}
    if verdict.get("injection") is True:
        return GuardResult(False, f"LLM classifier: {verdict.get('reason', '')}", **tokens)
    return GuardResult(True, str(verdict.get("reason", "")), modified=message, **tokens)


def _scrub(node: Any, path: str, flagged: list[str]) -> Any:
    if isinstance(node, dict):
        return {k: _scrub(v, f"{path}.{k}" if path else k, flagged) for k, v in node.items()}
    if isinstance(node, list):
        return [_scrub(v, f"{path}[{i}]", flagged) for i, v in enumerate(node)]
    if isinstance(node, str) and _match(node, _TOOL_RE):
        flagged.append(path or "<root>")
        return HIDDEN_TEXT
    return node


def sanitize_tool_output(result: dict[str, Any]) -> GuardResult:
    """Hide suspicious text fields in tool data and always wrap it as untrusted."""
    flagged: list[str] = []
    data = _scrub(result.get("data"), "data", flagged) if "data" in result else None
    cleaned = {**result, "data": data} if "data" in result else dict(result)
    reason = f"ẩn {len(flagged)} trường nghi injection" if flagged else ""
    return GuardResult(True, reason, modified={"untrusted_data": cleaned}, flagged=flagged)


# --- PII -------------------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w+])(?:\+84|0)(?:[\s.-]?\d){9}(?!\d)")


def canonical_pii(value: str) -> str:
    if "@" in value:
        return value.strip().lower()
    digits = re.sub(r"\D", "", value)
    return "0" + digits[2:] if digits.startswith("84") else digits


def collect_pii(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for v in node.values():
            found |= collect_pii(v)
    elif isinstance(node, list):
        for v in node:
            found |= collect_pii(v)
    elif isinstance(node, str):
        found |= {canonical_pii(m) for m in EMAIL_RE.findall(node)}
        found |= {canonical_pii(m.group(0)) for m in PHONE_RE.finditer(node)}
    return found


def redact_pii(text: str, allowed: set[str]) -> GuardResult:
    """Mask emails/phone numbers in the answer that do not belong to the current user."""
    redacted: list[str] = []

    def repl(m: re.Match) -> str:
        if canonical_pii(m.group(0)) in allowed:
            return m.group(0)
        redacted.append(m.group(0))
        return REDACTED

    out = PHONE_RE.sub(repl, EMAIL_RE.sub(repl, text))
    reason = f"che {len(redacted)} PII không thuộc user" if redacted else ""
    return GuardResult(True, reason, modified=out, flagged=redacted)


# --- GuardAgent: the four layers as one component, explicit about what is on and off -----------------

# Which documented mitigation each layer implements. [OWASP] = OWASP Top 10 for LLM Applications 2025,
# LLM01 Prompt Injection "Prevention and Mitigation Strategies"; [Greshake] = Greshake et al., AISec '23.
LAYERS: dict[str, dict[str, str]] = {
    "input_rules": {
        "title": "Lọc đầu vào bằng luật (regex)", "stage": "input",
        "mitigates": "Prompt injection trực tiếp",
        "reference": "[OWASP] LLM01 #3 Implement input and output filtering",
        "when_off": "Tin nhắn đi thẳng vào LLM; chỉ còn system prompt (quy tắc 8) chống lại yêu cầu đọc prompt, nhập vai.",
    },
    "input_llm": {
        "title": "Bộ phân loại injection bằng LLM", "stage": "input",
        "mitigates": "Prompt injection trực tiếp diễn đạt khéo (regex không bắt được)",
        "reference": "[OWASP] LLM01 #3 Implement input and output filtering (semantic filter)",
        "when_off": "Không tốn thêm một lời gọi LLM; câu tấn công diễn đạt lại chỉ bị chặn nếu khớp regex.",
    },
    "tool_output": {
        "title": "Tách và đánh dấu dữ liệu từ công cụ", "stage": "tool",
        "mitigates": "Prompt injection gián tiếp qua dữ liệu (ghi chú đơn, mô tả sản phẩm, lý do hoàn tiền)",
        "reference": "[OWASP] LLM01 #6 Segregate and identify external content; [Greshake]",
        "when_off": "Kết quả công cụ được đưa NGUYÊN VĂN cho LLM, không quét, không bọc untrusted_data.",
    },
    "output_pii": {
        "title": "Che thông tin cá nhân trong câu trả lời", "stage": "output",
        "mitigates": "Lộ email/SĐT của người khác",
        "reference": "[OWASP] LLM01 #3 (output filtering), LLM02 Sensitive Information Disclosure",
        "when_off": "Câu trả lời được gửi nguyên văn, kể cả email/SĐT không thuộc người dùng.",
    },
}

# Named configurations, same names as eval/run_eval.py (Bảng 1 of the report).
PRESETS: dict[str, dict[str, bool]] = {
    "none": {"input_rules": False, "input_llm": False, "tool_output": False, "output_pii": False},
    "rules": {"input_rules": True, "input_llm": False, "tool_output": False, "output_pii": False},
    "rules_tool": {"input_rules": True, "input_llm": False, "tool_output": True, "output_pii": False},
    "full": {"input_rules": True, "input_llm": True, "tool_output": True, "output_pii": True},
}

# action of one layer on one item: what happened, in words the UI can show
#   off      layer disabled for this request (nothing checked)
#   pass     checked, nothing found
#   block    message rejected (input layers)
#   wrap     tool result marked as untrusted_data, nothing suspicious
#   hide     tool result marked and suspicious fields replaced by HIDDEN_TEXT
#   redact   personal data replaced by REDACTED in the answer
#   skip     not applicable (e.g. a pending_approval result generated by the Gateway itself)


class GuardAgent:
    """Runs the enabled layers, records one event per layer and item (also for disabled layers) in the trace.

    The orchestrator (loop.py) calls check_input before the first LLM call, inspect_tool_result on every tool result
    and check_output on the final answer. summary() is returned to the client so the UI shows exactly which layers
    ran and what they did.
    """

    def __init__(self, config: GuardConfig, llm: LLMClient, tracer: Any):
        self.config = config
        self.llm = llm
        self.tracer = tracer
        self.events: list[dict[str, Any]] = []

    def _record(self, layer: str, step: int, action: str, reason: str = "", **extra: Any) -> None:
        enabled = getattr(self.config, layer)
        event = {"layer": layer, "enabled": enabled, "action": action, "reason": reason, "step": step, **extra}
        self.events.append(event)
        if self.tracer is not None:
            self.tracer.event("guard", step, {**event, "allowed": action != "block"})

    def check_input(self, message: str) -> GuardResult:
        """Both input layers in order; the first block wins. Tokens of the classifier are reported."""
        tokens = {"prompt_tokens": 0, "completion_tokens": 0}
        for layer, check in (("input_rules", lambda: check_input_rules(message)),
                             ("input_llm", lambda: check_input_llm(message, self.llm))):
            if not getattr(self.config, layer):
                self._record(layer, 0, "off", LAYERS[layer]["when_off"])
                continue
            g = check()
            tokens["prompt_tokens"] += g.prompt_tokens
            tokens["completion_tokens"] += g.completion_tokens
            self._record(layer, 0, "pass" if g.allowed else "block", g.reason, flagged=g.flagged)
            if not g.allowed:
                return GuardResult(False, g.reason, flagged=g.flagged, **tokens)
        return GuardResult(True, "", modified=message, **tokens)

    def inspect_tool_result(self, tool: str, result: dict[str, Any], step: int) -> Any:
        """What the LLM gets to see of one tool result."""
        if result.get("status") == "pending_approval":
            self._record("tool_output", step, "skip", "kết quả do Gateway sinh (tạo ticket), không phải dữ liệu",
                         tool=tool)
            return result
        if not self.config.tool_output:
            self._record("tool_output", step, "off", LAYERS["tool_output"]["when_off"], tool=tool)
            return result
        g = sanitize_tool_output(result)
        self._record("tool_output", step, "hide" if g.flagged else "wrap", g.reason or "bọc untrusted_data",
                     tool=tool, flagged=g.flagged)
        return g.modified

    def check_output(self, answer: str, allowed_pii: set[str], step: int) -> str:
        if not self.config.output_pii:
            self._record("output_pii", step, "off", LAYERS["output_pii"]["when_off"])
            return answer
        g = redact_pii(answer, allowed_pii)
        self._record("output_pii", step, "redact" if g.flagged else "pass", g.reason, redacted=len(g.flagged))
        return g.modified

    def summary(self) -> dict[str, Any]:
        return {"config": self.config.as_dict(), "events": self.events}
