"""Hình 2 — luồng multi-agent của OpsPilot V2, cùng phong cách với Hình 1 (khối bo góc, màu nhạt, số bước tròn)."""
from html import escape
from pathlib import Path

W, H = 1600, 1030
FONT = "'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "Menlo, 'SF Mono', monospace"

C = {  # fill, stroke
    "gray": ("#F4F4F6", "#A9A9B2"),
    "blue": ("#E9F0FD", "#4C7BD9"),
    "purple": ("#F3EEFC", "#8A63D2"),
    "green": ("#E8F5EC", "#3B9B5B"),
    "red": ("#FDEDED", "#D9534F"),
    "orange": ("#FFF4E5", "#F0A23B"),
}
DARK, MUTED = "#1F2A44", "#5B6475"

out: list[str] = []


def text(x, y, s, size=15, weight=400, fill=DARK, anchor="middle", family=FONT, italic=False):
    style = "font-style:italic;" if italic else ""
    out.append(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
               f'fill="{fill}" text-anchor="{anchor}" style="{style}">{escape(s)}</text>')


def box(x, y, w, h, color, title, lines=(), title_size=19, dashed=False, radius=10, line_size=13.5,
        align="middle", mono_lines=False):
    fill, stroke = C[color]
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" '
               f'stroke-width="2"{dash}/>')
    cx = x + w / 2 if align == "middle" else x + 14
    if title:
        text(cx, y + 28, title, title_size, 700, anchor=align)
    for i, ln in enumerate(lines):
        weight, s = (700, ln[1:]) if ln.startswith("!") else (400, ln)
        text(cx, y + 52 + i * 19, s, line_size, weight, fill=DARK if weight == 700 else MUTED, anchor=align,
             family=MONO if mono_lines and not s.startswith("(") else FONT)


def arrow(points, dashed=False, both=False, color=DARK, width=2):
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    start = ' marker-start="url(#head-start)"' if both else ""
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash}{start} '
               f'marker-end="url(#head)"/>')


def step(x, y, n):
    out.append(f'<circle cx="{x}" cy="{y}" r="14" fill="{DARK}"/>')
    text(x, y + 5.5, str(n), 15, 700, fill="#FFFFFF")


def label(x, y, s, anchor="middle", size=13):
    text(x, y, s, size, 400, fill=MUTED, anchor=anchor, italic=True)


# ---- user interface ------------------------------------------------------------------------------
box(600, 18, 400, 66, "gray", "UI (Streamlit)", ["Chat · công tắc guardrails · Trace"])

# ---- agent service container ---------------------------------------------------------------------
fill, stroke = C["blue"]
out.append(f'<rect x="30" y="120" width="1190" height="615" rx="14" fill="#F8FAFE" stroke="{stroke}" '
           f'stroke-width="2" stroke-dasharray="9 6"/>')
text(50, 148, "Agent service — Python · FastAPI · orchestrator multi-agent", 16, 700, fill=stroke, anchor="start")

box(410, 168, 420, 64, "purple", "GuardAgent — lớp 1, 2", ["lọc đầu vào: regex · bộ phân loại LLM"], 17)
box(880, 168, 320, 64, "purple", "GuardAgent — lớp 4", ["che PII trong câu trả lời"], 17)
box(410, 268, 420, 72, "blue", "Router", ["1 lời gọi LLM, không công cụ → {agent, reason}"])

agents = [  # (text, kind): kind = desc | tool | write
    ("Order agent", "Đơn hàng & Vận chuyển",
     [("list_my_orders · search_orders", "tool"), ("get_order · get_shipment", "tool"),
      ("cancel_order", "write"), ("update_shipping_address", "write"), ("update_shipment_status", "write")]),
    ("Sales agent", "Sản phẩm & Đặt hàng",
     [("search_products · get_product", "tool"), ("check_stock · quote_order", "tool"), ("get_order", "tool"),
      ("place_order", "write"), ("pay_order", "write")]),
    ("Refund agent", "Thanh toán & Hoàn tiền",
     [("get_payment · get_order", "tool"), ("check_refund_eligibility", "tool"), ("list_refund_requests", "tool"),
      ("refund_payment (rủi ro cao)", "write"), ("approve_refund · reject_refund", "write")]),
    ("General agent", "Tiếp nhận",
     [("lời chào, câu ngoài phạm vi", "desc"), ("không có công cụ dữ liệu", "desc")]),
]
AX, AW, AY, AH, GAP = 50, 275, 390, 205, 18
for i, (title, scope, tools) in enumerate(agents):
    x = AX + i * (AW + GAP)
    box(x, AY, AW, AH, "blue", title, [scope], 18, line_size=14)
    for j, (t, kind) in enumerate(tools):
        text(x + AW / 2, AY + 84 + j * 22, t, 12.5 if kind != "desc" else 14,
             700 if kind == "write" else 400, fill="#B23A36" if kind == "write" else MUTED,
             family=FONT if kind == "desc" else MONO)

# handoff: dashed bracket under the agents
hy = AY + AH + 25
xs = [AX + i * (AW + GAP) + AW / 2 for i in range(4)]
out.append(f'<path d="M {xs[0]} {hy} L {xs[3]} {hy}" fill="none" stroke="{stroke}" stroke-width="2" '
           f'stroke-dasharray="7 5"/>')
for x in xs:
    arrow([(x, hy), (x, AY + AH + 3)], dashed=True, color=stroke)
text(xs[0] - 40, hy + 22, "transfer_to_agent: chuyển việc giữa agent (tối đa 2 lần/lượt)", 13.5, 700,
     fill=stroke, anchor="start")

box(620, 662, 560, 54, "purple", "GuardAgent — lớp 3: quét kết quả công cụ, bọc untrusted_data", [], 15)

# ---- LLM -----------------------------------------------------------------------------------------
box(1270, 262, 300, 76, "gray", "LLM (OpenAI)", ["gpt-4o-mini · function calling"])

# ---- gateway + backends --------------------------------------------------------------------------
box(470, 780, 560, 82, "green", "Tool Gateway",
    ["TypeScript · Fastify · registry (Swagger) · authz · Ajv", "confirm_args · rate limit · idempotency · audit"],
    line_size=13)
box(60, 787, 330, 68, "red", "Redis", ["rate limit · khoá idempotency"], 17)
box(1110, 787, 400, 68, "orange", "Approval service", ["NestJS · human-in-the-loop (ticket)"], 17)
services = [("Order", "đơn hàng · báo giá"), ("Product", "sản phẩm · tồn kho"),
            ("Payment", "thanh toán · hoàn tiền"), ("Shipping", "vận chuyển")]
for i, (name, sub) in enumerate(services):
    box(120 + i * 350, 915, 310, 64, "red", name, [sub], 17)
out.append('<rect x="100" y="993" width="1390" height="24" rx="8" fill="none" stroke="#6C8FD6" '
           'stroke-width="1.5" stroke-dasharray="6 5"/>')
text(795, 1010, "gRPC giữa các microservice (trừ/cộng kho, thanh toán, huỷ vận đơn, đồng bộ trạng thái qua outbox)",
     12.5, 400, fill="#4C6CB5")

# ---- arrows and numbered steps -----------------------------------------------------------------------
arrow([(700, 84), (700, 166)])                            # 1 message -> input guard
step(676, 104, 1); label(718, 108, "tin nhắn", "start")
arrow([(620, 232), (620, 266)])                           # 2 -> router
step(596, 249, 2); label(640, 254, "cho qua", "start")
arrow([(620, 340), (620, 388)])                           # router -> chosen agent
label(640, 370, "giao cho agent được chọn", "start")
arrow([(830, 300), (1268, 300)], both=True)               # router <-> LLM
label(950, 291, "phân loại tin nhắn")
arrow([(1204, 440), (1240, 440), (1240, 326), (1268, 326)], both=True)   # agents <-> LLM
step(1240, 384, 3)
label(1262, 379, "messages + công cụ", "start"); label(1262, 396, "của agent đang xử lý", "start")
arrow([(575, AY + AH), (575, 778)])                       # 4 agent -> gateway (/invoke)
step(551, 752, 4); label(597, 757, "/invoke · JWT người dùng · chỉ công cụ của agent", "start")
arrow([(1000, 778), (1000, 718)])                         # 7 result -> layer 3 -> agent
arrow([(1000, 662), (1000, AY + AH + 2)])
step(1024, 752, 7); label(1048, 757, "kết quả", "start")
arrow([(750, 862), (750, 913)])                           # 5 gateway -> services
step(726, 888, 5); label(772, 893, "REST (Swagger)", "start")
arrow([(1030, 821), (1108, 821)], both=True)              # 6 gateway <-> approval
step(1069, 800, 6); label(1069, 872, "ticket (gRPC)")
arrow([(470, 821), (392, 821)], both=True)                # gateway <-> redis
arrow([(1110, 388), (1110, 234)])                         # final answer -> PII layer
label(1122, 362, "câu trả lời", "start")
arrow([(1110, 168), (1110, 51), (1002, 51)])              # 8 -> UI
step(1110, 104, 8); label(1132, 108, "trả lời", "start")

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
  <marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="{DARK}"/></marker>
  <marker id="head-start" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="{DARK}"/></marker>
</defs>
<rect width="{W}" height="{H}" fill="#FFFFFF"/>
{chr(10).join(out)}
</svg>'''
here = Path(__file__).parent
(here / "fig2.svg").write_text(svg, encoding="utf-8")
(here / "fig2.html").write_text(
    f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:#fff}}</style>{svg}', encoding="utf-8")
print("ok")
