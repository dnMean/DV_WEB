"""OpsPilot UI: login, chat, approval dashboard, tool registry, trace viewer."""
import json
import os

import httpx
import streamlit as st

AUTH_URL = os.getenv("AUTH_URL", "http://localhost:8001")
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8020")
APPROVAL_URL = os.getenv("APPROVAL_URL", "http://localhost:8011")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8010")
SHIPPING_URL = os.getenv("SHIPPING_URL", "http://localhost:8005")
ORDER_URL = os.getenv("ORDER_URL", "http://localhost:8002")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:8004")

STATUS_BADGE = {
    "done": ("✅", "Hoàn tất"),
    "pending_approval": ("⏳", "Chờ nhân viên duyệt"),
    "blocked": ("🛡️", "Bị chặn bởi guardrail"),
    "max_steps": ("🔁", "Vượt số bước tối đa"),
    "budget_exceeded": ("💸", "Vượt ngân sách token"),
    "error": ("⚠️", "Lỗi"),
}

st.set_page_config(page_title="OpsPilot", page_icon="🧭", layout="wide")
ss = st.session_state
ss.setdefault("token", None)
ss.setdefault("conversation_id", None)
ss.setdefault("chat_log", [])  # [{"role", "content", "meta"}]


def api(method: str, url: str, **kwargs) -> httpx.Response | None:
    headers = kwargs.pop("headers", {})
    if ss.token:
        headers["Authorization"] = f"Bearer {ss.token}"
    try:
        return httpx.request(method, url, headers=headers, timeout=120.0, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"Không gọi được {url}: {exc}")
        return None


def show_error(resp: httpx.Response) -> None:
    try:
        body = resp.json()
        st.error(f"{resp.status_code} {body.get('error')}: {body.get('message')}")
    except ValueError:
        st.error(f"{resp.status_code}: {resp.text[:300]}")


# --- pages ------------------------------------------------------------------------------------

def page_login() -> None:
    st.title("🧭 OpsPilot")
    st.caption("Tài khoản demo: alice / bob (customer), staff1 (staff) — mật khẩu password123")
    with st.form("login"):
        username = st.text_input("Tên đăng nhập", value="alice")
        password = st.text_input("Mật khẩu", type="password", value="password123")
        if st.form_submit_button("Đăng nhập", type="primary"):
            resp = api("POST", f"{AUTH_URL}/auth/login", json={"username": username, "password": password})
            if resp is None:
                return
            if resp.is_success:
                body = resp.json()
                ss.update(token=body["access_token"], role=body["role"], user_id=body["user_id"],
                          username=username, conversation_id=None, chat_log=[])
                convs = _list_conversations()
                if convs:
                    ss.conversation_id = convs[0]["id"]
                    _reload_conversation()
                st.rerun()
            else:
                show_error(resp)


def _render_steps(meta: dict) -> None:
    badge, label = STATUS_BADGE.get(meta.get("status"), ("❔", meta.get("status")))
    cols = st.columns([2, 3, 3])
    cols[0].caption(f"{badge} {label}")
    if meta.get("ticket_id"):
        cols[1].caption(f"🎫 Ticket: `{meta['ticket_id']}`")
    usage = meta.get("usage") or {}
    cols[2].caption(f"🔢 {usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)} tokens · "
                    f"{meta.get('latency_ms', 0):.0f} ms")
    with st.expander(f"Trace ({len(meta.get('steps', []))} tool call)"):
        st.caption(f"trace_id: `{meta.get('trace_id')}`")
        for s in meta.get("steps", []):
            icon = {"ok": "🟢", "pending_approval": "🟡"}.get(s.get("status"), "🔴")
            st.markdown(f"{icon} **Bước {s['step']}** `{s['tool']}` → `{s.get('status')}`"
                        + (f" ({s['error']})" if s.get("error") else ""))
            st.code(json.dumps(s.get("arguments"), ensure_ascii=False), language="json")


def _list_conversations() -> list[dict]:
    resp = api("GET", f"{AGENT_URL}/conversations")
    return resp.json() if resp is not None and resp.is_success else []


def _reload_conversation() -> None:
    resp = api("GET", f"{AGENT_URL}/conversations/{ss.conversation_id}")
    if resp is None or not resp.is_success:
        return
    log = []
    for m in resp.json()["messages"]:
        if m["role"] == "user":
            log.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant" and m.get("content") and not m.get("tool_calls"):
            log.append({"role": "assistant", "content": m["content"]})
        elif m["kind"] == "notification":
            log.append({"role": "notification", "content": m["content"]})
    ss.chat_log = log


def page_chat() -> None:
    st.title("💬 Chat với trợ lý CSKH")
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("🆕 Hội thoại mới"):
        ss.conversation_id, ss.chat_log = None, []
        st.rerun()
    if c2.button("🔄 Tải lại", disabled=not ss.conversation_id, help="Xem thông báo duyệt mới"):
        _reload_conversation()
        st.rerun()
    convs = _list_conversations()
    if convs:
        ids = [c["id"] for c in convs]
        if ss.conversation_id and ss.conversation_id not in ids:
            ids.insert(0, ss.conversation_id)
        labels = {c["id"]: f"{c['last_message_at'][5:16].replace('T', ' ')} · {c['title'] or '(trống)'}" for c in convs}
        current = ss.conversation_id if ss.conversation_id in ids else None
        picked = c3.selectbox(
            "Hội thoại", ids, index=ids.index(current) if current else None,
            format_func=lambda i: labels.get(i, i[:8]), placeholder="Chọn hội thoại cũ...",
            label_visibility="collapsed",
        )
        if picked and picked != ss.conversation_id:
            ss.conversation_id = picked
            _reload_conversation()
            st.rerun()

    for item in ss.chat_log:
        if item["role"] == "notification":
            st.info(f"🔔 {item['content']}")
            continue
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
            if item.get("meta"):
                _render_steps(item["meta"])

    placeholder = ("Vd: Cập nhật đơn 1003 đã lấy hàng · Cập nhật đơn 1002 đã giao · Đồng ý hoàn tiền đơn 1040"
                   if ss.get("role") == "staff" else "Hỏi về đơn hàng, thanh toán, vận chuyển, sản phẩm...")
    message = st.chat_input(placeholder)
    if not message:
        return
    ss.chat_log.append({"role": "user", "content": message})
    with st.spinner("Đang xử lý..."):
        resp = api("POST", f"{AGENT_URL}/chat", json={"conversation_id": ss.conversation_id, "message": message})
    if resp is None:
        return
    if not resp.is_success:
        show_error(resp)
        return
    body = resp.json()
    ss.conversation_id = body["conversation_id"]
    ss.chat_log.append({"role": "assistant", "content": body["answer"], "meta": body})
    st.rerun()


def _ticket_card(t: dict, actionable: bool) -> None:
    args = t["arguments"]
    title = f"`{t['id'][:8]}` · `{t['tool']}` · user {t['user_id']} · {t['status']}"
    if t["tool"] == "refund_payment":
        title = (f"`{t['id'][:8]}` · 💰 Hoàn {args.get('amount', 0):,}đ đơn {args.get('order_id')} · "
                 f"user {t['user_id']} · {t['status']}")
    with st.expander(title, expanded=actionable):
        st.caption(f"ticket `{t['id']}` · conversation `{t['conversation_id']}` · {t['created_at'][:19]}")
        st.json(args)
        if t.get("review_note"):
            st.caption(f"Ghi chú duyệt: {t['review_note']}")
        if t.get("result"):
            st.json(t["result"], expanded=False)
        if actionable:
            note = st.text_input("Ghi chú", key=f"note-{t['id']}")
            a, r = st.columns(2)
            for col, action, label in ((a, "approve", "✅ Approve"), (r, "reject", "❌ Reject")):
                if col.button(label, key=f"{action}-{t['id']}", type="primary" if action == "approve" else "secondary"):
                    resp = api("POST", f"{APPROVAL_URL}/tickets/{t['id']}/{action}", json={"note": note})
                    if resp is not None and resp.is_success:
                        st.success(f"Ticket → {resp.json()['status']}")
                        st.rerun()
                    elif resp is not None:
                        show_error(resp)


def page_approvals() -> None:
    st.title("🧾 Duyệt yêu cầu")
    if st.button("🔄 Làm mới"):
        st.rerun()
    resp = api("GET", f"{APPROVAL_URL}/tickets", params={"status": "PENDING"})
    if resp is None:
        return
    if not resp.is_success:
        show_error(resp)
        return
    pending = resp.json()
    st.subheader(f"Đang chờ ({len(pending)})")
    if not pending:
        st.caption("Không có yêu cầu nào.")
    for t in pending:
        _ticket_card(t, actionable=True)

    st.subheader("Đã xử lý gần đây")
    resp = api("GET", f"{APPROVAL_URL}/tickets", params={"limit": 20})
    if resp is not None and resp.is_success:
        for t in [t for t in resp.json() if t["status"] != "PENDING"]:
            _ticket_card(t, actionable=False)


def page_tools() -> None:
    st.title("🧰 Tool registry")
    resp = api("GET", f"{GATEWAY_URL}/tools/meta")
    if resp is None:
        return
    if not resp.is_success:
        show_error(resp)
        return
    tools = resp.json()
    st.dataframe(
        [{"name": t["name"], "risk": t["risk"], "roles": ", ".join(t["roles"]), "method": t["method"],
          "path": t["path"], "service": t["service_url"], "description": t["description"]} for t in tools],
        width="stretch", hide_index=True,
    )
    name = st.selectbox("Xem JSON Schema tham số", [t["name"] for t in tools])
    st.json(next(t for t in tools if t["name"] == name)["parameters"])

    st.subheader("Audit log gần nhất")
    resp = api("GET", f"{GATEWAY_URL}/audit", params={"limit": 30})
    if resp is not None and resp.is_success:
        st.dataframe(resp.json(), width="stretch", hide_index=True)


ORDER_LABEL = {
    "PENDING": "🕓 Chờ thanh toán", "PAID": "💳 Đã thanh toán", "SHIPPING": "🚚 Đang giao",
    "DELIVERED": "✅ Đã giao", "CANCELLED": "⛔ Đã huỷ", "REFUNDED": "↩️ Đã hoàn tiền",
}
SHIP_LABEL = {
    "WAITING_PICKUP": "📦 Chờ lấy hàng", "IN_TRANSIT": "🚚 Đang giao", "DELIVERED": "✅ Đã giao",
    "CANCELLED": "⛔ Đã huỷ",
}
SHIP_STEPS = ["WAITING_PICKUP", "IN_TRANSIT", "DELIVERED"]
LOCATIONS = ["Kho TP.HCM", "Kho trung chuyển Đà Nẵng", "Kho Hà Nội", "Bưu cục phát"]


def _money(v: int) -> str:
    return f"{v:,}đ".replace(",", ".")


def _load_orders_with_shipments() -> list[dict]:
    orders = api("GET", f"{ORDER_URL}/orders/search", params={"limit": 200})
    shipments = api("GET", f"{SHIPPING_URL}/shipments")
    for resp in (orders, shipments):
        if resp is not None and not resp.is_success:
            show_error(resp)
    if orders is None or shipments is None or not orders.is_success or not shipments.is_success:
        return []
    by_order = {sh["order_id"]: sh for sh in shipments.json()}
    return [{"order": o, "shipment": by_order.get(o["id"])} for o in orders.json()["orders"]]


def _progress(status: str) -> None:
    if status == "CANCELLED":
        st.error("⛔ Vận đơn đã huỷ (đơn được hoàn tiền trước khi giao) — không còn thao tác.")
        return
    reached = SHIP_STEPS.index(status)
    cols = st.columns(len(SHIP_STEPS))
    for i, (col, step) in enumerate(zip(cols, SHIP_STEPS)):
        mark = "🟢" if i < reached else ("🔵" if i == reached else "⚪")
        col.markdown(f"{mark} **{SHIP_LABEL[step]}**" if i == reached else f"{mark} {SHIP_LABEL[step]}")
    st.progress(reached / (len(SHIP_STEPS) - 1))


def _advance(order_id: int, status: str, location: str, description: str) -> None:
    r = api("POST", f"{SHIPPING_URL}/shipments/{order_id}/advance",
            json={"status": status, "location": location, "description": description})
    if r is not None and r.is_success:
        st.toast(f"Đơn #{order_id}: {SHIP_LABEL[status]}", icon="✅")
        st.rerun()
    elif r is not None:
        show_error(r)


def page_shipments() -> None:
    st.title("🚚 Vận chuyển")
    st.caption("Kho / đơn vị vận chuyển cập nhật vận đơn. Trạng thái đơn hàng tự đồng bộ sang Order.")
    rows = _load_orders_with_shipments()
    if not rows:
        st.info("Chưa có đơn hàng.")
        return

    f1, f2 = st.columns(2)
    ship_filter = f1.multiselect("Lọc vận đơn", list(SHIP_LABEL), format_func=SHIP_LABEL.get,
                                 default=["WAITING_PICKUP", "IN_TRANSIT"])
    user_filter = f2.selectbox("Khách", [None, 1, 2], format_func=lambda u: "Tất cả" if u is None else
                               {1: "alice (1)", 2: "bob (2)"}.get(u, str(u)))
    rows = [r for r in rows if r["shipment"] and (not ship_filter or r["shipment"]["status"] in ship_filter)
            and (user_filter is None or r["order"]["user_id"] == user_filter)]
    st.caption(f"{len(rows)} vận đơn")
    if not rows:
        st.info("Không có vận đơn nào khớp bộ lọc.")
        return
    st.dataframe(
        [{
            "Mã đơn": f"#{r['order']['id']}",
            "Người nhận": r["shipment"]["recipient_name"],
            "Sản phẩm": r["order"]["items"],
            "Đơn hàng": ORDER_LABEL.get(r["order"]["status"], r["order"]["status"]),
            "Vận đơn": SHIP_LABEL.get(r["shipment"]["status"], ""),
            "Đã hoàn": _money(r["order"]["refunded_amount"]) if r["order"]["refunded_amount"] else "",
        } for r in rows],
        width="stretch", hide_index=True, height=min(38 * (len(rows) + 1), 360),
    )

    by_id = {r["order"]["id"]: r for r in rows}
    if ss.get("ship_order") not in by_id:
        ss["ship_order"] = next(iter(by_id))
    order_id = st.selectbox(
        "Chọn đơn cần cập nhật", list(by_id), key="ship_order",
        format_func=lambda i: f"#{i} · {by_id[i]['order']['items']} · {SHIP_LABEL[by_id[i]['shipment']['status']]}",
    )
    order, shipment = by_id[order_id]["order"], by_id[order_id]["shipment"]

    with st.container(border=True):
        c = st.columns(3)
        c[0].metric("Vận đơn", SHIP_LABEL[shipment["status"]])
        c[1].metric("Đơn hàng", ORDER_LABEL.get(order["status"], order["status"]))
        c[2].metric("Đã hoàn", _money(order["refunded_amount"]))
        st.caption(f"{shipment['carrier']} · mã vận đơn **{shipment['tracking_code']}** · "
                   f"{shipment['recipient_name']} · {shipment['address']}")
        _progress(shipment["status"])

    status = shipment["status"]
    if status in ("WAITING_PICKUP", "IN_TRANSIT"):
        st.subheader("Cập nhật")
        choice = st.selectbox("Vị trí hiện tại", LOCATIONS + ["Địa chỉ người nhận", "Khác…"], key=f"loc-{order_id}")
        if choice == "Khác…":
            location = st.text_input("Nhập vị trí", key=f"loc-custom-{order_id}").strip()
        elif choice == "Địa chỉ người nhận":
            location = shipment["address"]
        else:
            location = choice
        if status == "WAITING_PICKUP":
            st.caption("Bước tiếp theo: đơn vị vận chuyển đến lấy hàng tại kho.")
            if st.button("📦 Xác nhận đã lấy hàng", type="primary", disabled=not location):
                _advance(order_id, "IN_TRANSIT", location, "Đã lấy hàng, đang vận chuyển")
        else:
            a, b = st.columns(2)
            if a.button("📍 Cập nhật vị trí", disabled=not location, width="stretch"):
                _advance(order_id, "IN_TRANSIT", location, f"Đang vận chuyển qua {location}")
            if b.button("✅ Xác nhận đã giao", type="primary", disabled=not location, width="stretch"):
                _advance(order_id, "DELIVERED", location, "Giao hàng thành công")
    elif status == "DELIVERED":
        st.success("✅ Đã giao xong — không còn thao tác vận chuyển.")

    st.subheader("Lịch sử")
    icons = {"WAITING_PICKUP": "📦", "IN_TRANSIT": "🚚", "DELIVERED": "✅", "CANCELLED": "⛔"}
    for e in reversed(shipment["events"]):
        st.markdown(f"{icons.get(e['status'], '•')} **{e['description']}**  \n"
                    f"<span style='opacity:.65'>{e['occurred_at'][:16].replace('T', ' ')} · {e['location']}</span>",
                    unsafe_allow_html=True)


PAY_LABEL = {"SUCCESS": "✅ Đã thanh toán", "PARTIALLY_REFUNDED": "↩️ Đã hoàn một phần", "REFUNDED": "↩️ Đã hoàn toàn bộ"}
METHOD_LABEL = {"COD": "Tiền mặt khi nhận", "CARD": "Thẻ", "BANK_TRANSFER": "Chuyển khoản", "E_WALLET": "Ví điện tử"}


def _load_my_orders(status: str | None) -> list[dict]:
    """Every order of the logged-in customer (GET /orders is paginated, 50 per page)."""
    orders, offset = [], 0
    while True:
        params = {"limit": 50, "offset": offset, **({"status": status} if status else {})}
        resp = api("GET", f"{ORDER_URL}/orders", params=params)
        if resp is None:
            return orders
        if not resp.is_success:
            show_error(resp)
            return orders
        page = resp.json()
        orders += page["orders"]
        if not page["has_more"] or offset >= 1000:
            return orders
        offset += page["limit"]


def _get_optional(url: str, **kwargs) -> dict | None:
    """GET that treats 404 as "not there yet" (e.g. no payment / shipment for a pending order)."""
    resp = api("GET", url, **kwargs)
    if resp is None or resp.status_code == 404:
        return None
    if not resp.is_success:
        show_error(resp)
        return None
    return resp.json()


def page_my_orders() -> None:
    st.title("📦 Đơn hàng của tôi")
    st.caption("Muốn huỷ đơn, thanh toán, đổi địa chỉ hay hoàn tiền: hãy nhắn cho trợ lý ở trang Chat.")
    status = st.selectbox("Trạng thái", [None, *ORDER_LABEL],
                          format_func=lambda s: "Tất cả" if s is None else ORDER_LABEL[s])
    orders = _load_my_orders(status)
    if not orders:
        st.info("Bạn chưa có đơn hàng nào." if status is None else "Không có đơn nào ở trạng thái này.")
        return

    c = st.columns(3)
    c[0].metric("Số đơn", len(orders))
    c[1].metric("Chờ thanh toán", sum(o["status"] == "PENDING" for o in orders))
    c[2].metric("Đang giao", sum(o["status"] in ("PAID", "SHIPPING") for o in orders))
    st.dataframe(
        [{
            "Mã đơn": f"#{o['id']}",
            "Ngày đặt": o["created_at"][:16].replace("T", " "),
            "Sản phẩm": o["items"],
            "Tổng tiền": _money(o["total"]),
            "Đã hoàn": _money(o["refunded_amount"]) if o["refunded_amount"] else "",
            "Trạng thái": ORDER_LABEL.get(o["status"], o["status"]),
        } for o in orders],
        width="stretch", hide_index=True, height=min(38 * (len(orders) + 1), 420),
    )

    by_id = {o["id"]: o for o in orders}
    order_id = st.selectbox("Xem chi tiết đơn", list(by_id),
                            format_func=lambda i: f"#{i} · {by_id[i]['items']} · {ORDER_LABEL.get(by_id[i]['status'])}")
    order = _get_optional(f"{ORDER_URL}/orders/{order_id}")
    if order is None:
        return
    payment = _get_optional(f"{PAYMENT_URL}/payments", params={"order_id": order_id})
    shipment = _get_optional(f"{SHIPPING_URL}/shipments/{order_id}")

    with st.container(border=True):
        c = st.columns(3)
        c[0].metric("Đơn hàng", ORDER_LABEL.get(order["status"], order["status"]))
        c[1].metric("Tổng tiền", _money(order["total"]))
        c[2].metric("Thanh toán", PAY_LABEL.get(payment["status"], payment["status"]) if payment else "Chưa thanh toán")
        st.dataframe(
            [{"Sản phẩm": i["name"], "Số lượng": i["qty"], "Đơn giá": _money(i["price"]),
              "Thành tiền": _money(i["qty"] * i["price"])} for i in order["items"]],
            width="stretch", hide_index=True,
        )
        if payment:
            st.caption(f"Thanh toán {_money(payment['amount'])} bằng {METHOD_LABEL.get(payment['method'], payment['method'])}"
                       + (f" · đã hoàn {_money(payment['refunded_amount'])}" if payment["refunded_amount"] else ""))
        if order["status"] == "PENDING":
            st.info(f"Đơn đang chờ thanh toán. Để thanh toán, nhắn trợ lý: *thanh toán đơn {order_id} bằng thẻ*.")

    st.subheader("Vận chuyển")
    if shipment is None:
        st.caption("Chưa có vận đơn (vận đơn được tạo sau khi thanh toán).")
        return
    st.caption(f"{shipment['carrier']} · mã vận đơn **{shipment['tracking_code']}** · "
               f"{shipment['recipient_name']} · {shipment['recipient_phone']} · {shipment['address']}")
    if shipment["status"] == "CANCELLED":
        st.warning("⛔ Vận đơn đã huỷ do đơn được hoàn tiền trước khi giao.")
    else:
        _progress(shipment["status"])
    icons = {"WAITING_PICKUP": "📦", "IN_TRANSIT": "🚚", "DELIVERED": "✅", "CANCELLED": "⛔"}
    for e in reversed(shipment["events"]):
        st.markdown(f"{icons.get(e['status'], '•')} **{e['description']}**  \n"
                    f"<span style='opacity:.65'>{e['occurred_at'][:16].replace('T', ' ')} · {e['location']}</span>",
                    unsafe_allow_html=True)


def page_trace() -> None:
    st.title("🔎 Trace")
    trace_id = st.text_input("trace_id")
    if not trace_id:
        return
    resp = api("GET", f"{AGENT_URL}/traces/{trace_id.strip()}")
    if resp is None:
        return
    if not resp.is_success:
        show_error(resp)
        return
    t = resp.json()
    c = st.columns(4)
    c[0].metric("Status", t["status"])
    c[1].metric("Prompt tokens", t["prompt_tokens"])
    c[2].metric("Completion tokens", t["completion_tokens"])
    c[3].metric("Latency", f"{(t['latency_ms'] or 0):.0f} ms")
    st.caption(f"Guard config: {t['guard_config']}")
    for e in t["events"]:
        extra = f" · {e['latency_ms']:.0f} ms" if e.get("latency_ms") else ""
        if e.get("prompt_tokens"):
            extra += f" · {e['prompt_tokens']}+{e['completion_tokens']} tok"
        flagged = e["type"] == "guard" and (e["payload"].get("flagged") or not e["payload"].get("allowed", True))
        with st.expander(f"{'🚩 ' if flagged else ''}[{e['step']}] {e['type']}{extra}", expanded=bool(flagged)):
            st.json(e["payload"])


# --- layout -----------------------------------------------------------------------------------

if not ss.token:
    page_login()
else:
    with st.sidebar:
        st.markdown(f"**{ss.username}** · `{ss.role}`")
        pages = {"Chat": page_chat}
        if ss.role == "customer":
            pages["Đơn hàng của tôi"] = page_my_orders
        if ss.role == "staff":
            pages.update({"Approvals": page_approvals, "Vận chuyển": page_shipments, "Tools": page_tools,
                          "Trace": page_trace})
        choice = st.radio("Trang", list(pages))
        if st.button("Đăng xuất"):
            for k in ("token", "role", "user_id", "username", "conversation_id"):
                ss.pop(k, None)
            ss.chat_log = []
            st.rerun()
    pages[choice]()
