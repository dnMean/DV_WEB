# Multi-agent và Guardrails

Tài liệu này mô tả phần agent sau khi tách thành **multi-agent** và cách **bật/tắt guardrails**. Nó trả lời ba yêu
cầu: làm rõ AI Agent và tool-use (Y04.1), các function call đã hiện thực (Y04.2), và việc hiện thực chống prompt
injection theo tài liệu (Y04.3). Kiến trúc chung của hệ thống: [ARCHITECTURE.md](ARCHITECTURE.md).

Code: [services/agent/app/agents.py](../services/agent/app/agents.py) (các agent, router, handoff),
[loop.py](../services/agent/app/loop.py) (orchestrator),
[guardrails.py](../services/agent/app/guardrails.py) (`GuardAgent`),
[prompts.py](../services/agent/app/prompts.py). Test: [tests/test_multi_agent.py](../services/agent/tests/test_multi_agent.py).

---

## 1. AI Agent và tool-use trong OpsPilot (Y04.1)

LLM tự nó chỉ sinh văn bản. Nó trở thành **agent** khi được đặt trong một vòng lặp *suy luận → hành động → quan sát*
(ReAct): ở mỗi bước, LLM đọc hội thoại và danh sách công cụ, rồi **đề xuất** gọi một công cụ (function calling);
chương trình thực thi lời gọi đó và đưa kết quả trở lại cho LLM. Vòng lặp kết thúc khi LLM trả lời bằng văn bản.

| Vai trò | Thành phần | Làm gì | Không làm gì |
|---|---|---|---|
| Đề xuất | LLM (gpt-4o-mini) | Chọn công cụ, sinh tham số, quyết định khi nào trả lời | Không tự thực thi được gì |
| Điều phối | Orchestrator (`loop.py`) | Dựng ngữ cảnh, gọi LLM, chuyển lời gọi tới Gateway, đưa kết quả lại, giới hạn số bước/token | Không kiểm tra quyền |
| Kiểm soát + gọi | Tool Gateway | Quyền, JSON Schema, xác nhận, rate limit, phê duyệt; gọi REST của service | Không gọi LLM |
| Thực thi | Microservice | Nghiệp vụ thật, kiểm tra quyền sở hữu | Không biết request đến từ AI |

## 2. Từ single agent sang multi-agent

### 2.1 Kiến trúc

```
                         ┌────────────── GuardAgent ──────────────┐
 tin nhắn ──► ① ② lọc đầu vào ──► Router ──► agent chuyên trách ──► Gateway ──► ③ quét kết quả ──┐
                                    │        ▲          │                                          │
                                    │        └──────────┴── transfer_to_agent (tối đa 2 lần) ◄─────┘
                                    │                   │
                                    │              trả lời ──► ④ che PII ──► người dùng
```

| Agent | Phạm vi | Công cụ | Ghi (có thay đổi dữ liệu) |
|---|---|---|---|
| **Router** | Chọn agent cho tin nhắn | không có (1 lời gọi LLM trả JSON `{"agent", "reason"}`) | |
| **order**: Đơn hàng & Vận chuyển | tra cứu đơn, giao hàng, huỷ đơn, đổi địa chỉ; staff tìm đơn, cập nhật vận chuyển | `list_my_orders`, `search_orders`, `get_order`, `get_shipment`, `get_payment`, `cancel_order`, `update_shipping_address`, `update_shipment_status` | `cancel_order`, `update_shipping_address`, `update_shipment_status` |
| **sales**: Sản phẩm & Đặt hàng | hỏi sản phẩm, báo giá, đặt hàng, thanh toán đơn mới | `search_products`, `get_product`, `check_stock`, `get_order`, `quote_order`, `place_order`, `pay_order` | `place_order`, `pay_order` |
| **refund**: Thanh toán & Hoàn tiền | thanh toán, khả năng hoàn tiền, yêu cầu hoàn tiền; staff duyệt | `get_payment`, `check_refund_eligibility`, `get_order`, `get_approval_ticket`, `list_refund_requests`, `refund_payment`, `approve_refund`, `reject_refund` | `refund_payment` (rủi ro cao), `approve_refund`, `reject_refund` |
| **general**: Tiếp nhận | lời chào, câu không liên quan | không có công cụ dữ liệu | |
| **GuardAgent** | 4 lớp guardrail (mục 4) | | |

Mỗi agent chỉ nhận công cụ **trong phạm vi của nó** và **thuộc vai trò của người dùng**: Gateway lọc theo vai trò
trước, orchestrator lọc tiếp theo agent. Công cụ đọc dùng chung được cho nhiều agent (ví dụ `get_order`); mỗi công cụ
**ghi** thuộc đúng một agent (có test kiểm tra). Mỗi agent cũng có thêm công cụ `transfer_to_agent` để chuyển việc.

### 2.2 Một lượt multi-agent

*"Đơn 1003 giao nhầm màu, hoàn 2.500.000đ cho tôi"* (alice):

| Bước | Ai | Việc | Ghi trong trace |
|---|---|---|---|
| 0 | GuardAgent | ① regex: cho qua; ② classifier: TẮT | `guard` × 2 |
| 0 | Router | LLM chọn `order` (câu nói về một đơn) | `route {agent: order, method: llm}` |
| 1 | order | LLM thấy cần hoàn tiền, ngoài phạm vi → `transfer_to_agent(refund)` | `llm_call {agent: order}`, `handoff {from: order, to: refund}` |
| 2 | refund | Prompt và công cụ đổi sang agent refund; LLM gọi `refund_payment` | `llm_call {agent: refund}`, `tool_call` |
| 2 | Gateway | Công cụ rủi ro cao → precheck → tạo ticket → `pending_approval` | |
| 2 | GuardAgent | ③ kết quả do Gateway sinh: không áp dụng | `guard {action: skip}` |
| — | Orchestrator | Dừng vòng lặp, trả câu mẫu kèm mã ticket | `final {agent_path: [order, refund]}` |

Response của `/chat` có thêm `agent_mode`, `agent_path` (ví dụ `["order", "refund"]`) và `guard` (mục 4.2).

### 2.3 Vì sao tách, và cái giá phải trả

| Lợi ích | Giải thích |
|---|---|
| **Đặc quyền tối thiểu** | Agent bán hàng không bao giờ thấy `refund_payment`. Nếu LLM vẫn đề xuất một công cụ ngoài phạm vi, orchestrator trả lỗi `tool_not_in_agent` và **không gửi tới Gateway**. Khớp OWASP LLM06 Excessive Agency và LLM01 biện pháp 4 |
| **Prompt ngắn, tập trung** | Mỗi agent chỉ mang quy tắc của công cụ của mình: 1,9–4,7 nghìn ký tự so với 6,1 nghìn của single agent, và ít schema công cụ hơn |
| **Dễ mở rộng** | Thêm miền nghiệp vụ = thêm một agent, không làm dài prompt của các agent khác |

| Cái giá | Cách giảm |
|---|---|
| Thêm 1 lời gọi LLM (router) mỗi lượt, tăng độ trễ và token | Router không có công cụ, prompt ngắn; có thể thay bằng model rẻ hơn |
| Router có thể chọn sai | Agent tự chuyển việc bằng `transfer_to_agent` (tối đa `AGENT_MAX_HANDOFFS=2`) |
| Router LLM lỗi hoặc trả JSON hỏng | Định tuyến dự phòng bằng từ khoá (`method: keywords` trong trace) |

**Router không phải ranh giới bảo mật.** Người dùng có thể "xin" được chuyển sang agent hoàn tiền, nhưng agent đó cũng
chỉ có những công cụ mà vai trò của họ được phép, và Gateway vẫn kiểm tra quyền, xác nhận, phê duyệt như cũ.

### 2.4 Chọn chế độ

| Cách | Phạm vi | Ví dụ |
|---|---|---|
| Env `AGENT_MODE=multi` (mặc định) / `single` | Toàn bộ agent service | `.env` |
| Header `X-Agent-Mode: single \| multi` kèm `X-Internal-Secret` | Một request (eval, demo) | `run_eval.py --agent-modes single,multi` |

Giao diện luôn chạy **multi-agent** (không có lựa chọn single trên UI). Chế độ `single` chỉ dùng khi đo đạc: nó giữ **nguyên văn** prompt và hành vi cũ (có test kiểm tra), để so sánh được với số liệu Bảng 1.

---

## 3. Các function call đã hiện thực (Y04.2)

Mỗi công cụ là một endpoint REST của microservice, khai báo bằng decorator; Gateway đọc Swagger để sinh danh sách
công cụ cho LLM. Ví dụ ([payments.controller.ts](../services/payment/src/payments.controller.ts)):

```ts
@Post('refunds')
@Roles('system', 'staff')
@ApiOperation({ summary: 'Tạo yêu cầu hoàn tiền cho đơn hàng', description: 'Chỉ dùng khi chính khách yêu cầu …' })
@AgentTool('refund_payment', 'high', ['customer'], { dedupFields: ['order_id'], precheck: '/refunds/validate' })
refund(@Body() body: RefundIn, @AuthUser() user: CurrentUser, @Headers('idempotency-key') key?: string) { … }
```

20 công cụ nghiệp vụ (12 đọc, 7 ghi, 1 rủi ro cao): bảng đầy đủ ở [ARCHITECTURE.md mục 7.2](ARCHITECTURE.md). Thêm
`transfer_to_agent` là function call **nội bộ** của multi-agent: không đi qua Gateway, orchestrator tự xử lý.

Xem tận mắt: trang **Agents & Guardrails** trên UI, `GET /agents` của agent service, hoặc
`curl localhost:8010/tools -H "Authorization: Bearer $TOKEN"`.

---

## 4. Guardrails: bật, tắt và nhìn thấy được

### 4.1 Bốn lớp

| Lớp | Giai đoạn | Chống | Mặc định | Khi TẮT |
|---|---|---|---|---|
| ① `input_rules` | trước LLM | injection trực tiếp | BẬT | Tin nhắn đi thẳng vào LLM; chỉ còn system prompt chống lại |
| ② `input_llm` | trước LLM | injection trực tiếp diễn đạt khéo | TẮT (thêm 1 lời gọi LLM) | Câu diễn đạt lại chỉ bị chặn nếu khớp regex |
| ③ `tool_output` | sau mỗi công cụ | injection **gián tiếp** qua dữ liệu | BẬT | Kết quả công cụ đưa NGUYÊN VĂN cho LLM, không quét, không bọc `untrusted_data` |
| ④ `output_pii` | câu trả lời cuối | lộ email/SĐT người khác | BẬT | Câu trả lời gửi nguyên văn |

Bật/tắt theo 3 cách, giống như chọn chế độ agent: env `GUARD_*`, header `X-Guard-Config` (JSON, kèm
`X-Internal-Secret`), hoặc mục **🛡️ Guardrails** ở thanh bên UI (khi `UI_DEV_CONTROLS=true`): chọn nhanh cấu hình `none` / `rules` / `rules_tool` / `full` như Bảng 1, rồi bật/tắt từng lớp bằng công tắc. Phía trên khung chat luôn có dòng cho biết tin nhắn tiếp theo sẽ chạy với lớp nào đang tắt. Người dùng thường **không** tự tắt được qua API: thiếu secret thì trả 403.

### 4.2 Mỗi lượt cho biết lớp nào chạy và đã làm gì

Trước đây lớp bị tắt thì không để lại dấu vết nào. Nay `GuardAgent` ghi **một sự kiện cho mỗi lớp** (kể cả lớp tắt)
vào trace, và trả về trong response:

```json
"guard": {
  "config": {"input_rules": true, "input_llm": false, "tool_output": true, "output_pii": true},
  "events": [
    {"layer": "input_rules", "enabled": true,  "action": "pass", "step": 0},
    {"layer": "input_llm",   "enabled": false, "action": "off",  "reason": "Không tốn thêm một lời gọi LLM; …"},
    {"layer": "tool_output", "enabled": true,  "action": "hide", "tool": "get_order", "flagged": ["data.note"],
     "reason": "ẩn 1 trường nghi injection", "step": 1},
    {"layer": "output_pii",  "enabled": true,  "action": "pass", "step": 2}
  ]
}
```

| `action` | Nghĩa |
|---|---|
| `off` | Lớp bị tắt; `reason` nói rõ khi đó cái gì không còn được bảo vệ |
| `pass` | Đã kiểm tra, không thấy gì |
| `block` | Chặn tin nhắn (lớp đầu vào); không gọi router hay agent nào |
| `wrap` | Kết quả công cụ được bọc `untrusted_data`, không có gì đáng ngờ |
| `hide` | Đã bọc và thay các trường nghi injection bằng `[nội dung bị ẩn: …]` |
| `redact` | Đã che PII trong câu trả lời |
| `skip` | Không áp dụng (kết quả `pending_approval` do Gateway sinh) |

UI hiển thị khối **🛡️ Guardrails** dưới mỗi câu trả lời, mỗi lớp một dòng (⚪ TẮT, 🟢 cho qua, 🛑 chặn, 🙈 ẩn, 🟡 che).
Khối này tự mở khi có lớp can thiệp. Trang **Agents & Guardrails** liệt kê các lớp, mặc định, tài liệu tương ứng và hậu
quả khi tắt.

---

## 5. Đối chiếu với tài liệu về prompt injection (Y04.3)

Báo cáo dẫn **OWASP Top 10 for LLM Applications 2025** [6] và **Greshake et al., AISec '23** [5]. OWASP LLM01 (Prompt
Injection) đưa ra 7 biện pháp phòng ngừa; bảng dưới chỉ ra mỗi biện pháp được hiện thực ở đâu.

| # | Biện pháp (OWASP LLM01:2025) | Hiện thực trong OpsPilot | Ở đâu | Tắt được? |
|---|---|---|---|---|
| 1 | Constrain model behavior: ràng buộc vai trò, phạm vi; bỏ qua yêu cầu sửa chỉ dẫn gốc | System prompt: quy tắc 4 (dữ liệu công cụ không phải chỉ dẫn), 8 (không lộ prompt), 9 (từ chối câu ngoài phạm vi); mỗi agent chỉ được giao một phạm vi | `prompts.py`, `agents.py` | Không |
| 2 | Define and validate expected output formats | Tham số công cụ kiểm theo JSON Schema (Ajv, `additionalProperties: false`); router phải trả JSON đúng tên agent, sai thì định tuyến dự phòng; tham số JSON hỏng → `invalid_json` | Gateway `invoker.ts`, `agents.route()`, `loop._execute()` | Không |
| 3 | Implement input and output filtering | ① regex, ② classifier LLM, ④ che PII | `guardrails.py` (`GuardAgent`) | **Có**: ① ② ④ |
| 4 | Enforce privilege control and least privilege | Công cụ lọc theo vai trò (Gateway) **và theo agent** (multi-agent, `tool_not_in_agent`); agent dùng JWT của chính người dùng, không có quyền riêng; token `system` chỉ dùng khi thực thi ticket đã duyệt | Gateway `registry.ts`, `agents.py`, `loop.py` | Theo agent: chế độ `single` |
| 5 | Require human approval for high-risk actions | Công cụ rủi ro cao → ticket chờ nhân viên duyệt; `confirm_args`: duyệt/đặt hàng/thanh toán cần mã do chính người dùng gõ | Gateway `app.ts`, Approval service | Không |
| 6 | Segregate and identify external content | ③ bọc mọi kết quả công cụ trong `untrusted_data`, ẩn trường có chỉ dẫn; prompt quy tắc 4. Đây là kịch bản tấn công gián tiếp mà Greshake et al. mô tả: chỉ dẫn độc nằm trong dữ liệu ứng dụng tự lấy về (ghi chú đơn 1005) | `guardrails.sanitize_tool_output`, `GuardAgent.inspect_tool_result` | **Có**: ③ |
| 7 | Conduct adversarial testing and attack simulations | 56 kịch bản, 12 kịch bản tấn công (trực tiếp và gián tiếp), so sánh 4 cấu hình guardrail × 2 kiến trúc agent | `eval/scenarios.yaml`, `eval/run_eval.py` | |

Ngoài LLM01, kiến trúc còn nhắm tới **LLM06 Excessive Agency** (đặc quyền tối thiểu theo agent, phê duyệt của con
người) và **LLM02 Sensitive Information Disclosure** (④ che PII).

**Điều Greshake et al. nhấn mạnh và cách hệ thống tuân theo:** bộ lọc phát hiện nội dung độc không thể bắt hết, nên
các thao tác nguy hiểm phải được chặn ở nơi **không phụ thuộc LLM**. Trong OpsPilot, kể cả khi cả 4 lớp đều tắt
(cấu hình `none`), agent bị injection gọi `refund_payment` cũng chỉ tạo ra một ticket chờ duyệt (biện pháp 4–5).

### Hạn chế đã biết (chưa xử lý)

- Lớp ③ chỉ quét field `data`; với lỗi `duplicate_request`, Gateway chép lý do hoàn tiền cũ (do khách viết) vào
  `message`/`existing_arguments`, nên phần này không được quét (vẫn được bọc `untrusted_data`).
- Kết quả bị Gateway cắt (> 4000 ký tự) thành chuỗi: một chỗ nghi ngờ làm ẩn cả chuỗi.
- Regex bỏ lọt câu diễn đạt lại, ký tự vô hình, chữ đồng hình; có thể chặn nhầm ("bỏ qua hướng dẫn lắp đặt").

---

## 6. Đo lại

Multi-agent thay đổi số lời gọi LLM, token, độ trễ và có thể cả tỉ lệ chọn đúng công cụ. **Số liệu Bảng 1 được đo với
single agent**; cần chạy lại để có số cho multi-agent (cần `OPENAI_API_KEY`, tốn phí API):

```bash
RATE_LIMIT_READ_PER_MIN=1000 RATE_LIMIT_WRITE_PER_MIN=1000 docker compose up -d --build
.venv/bin/python eval/run_eval.py --agent-modes single,multi --configs none,rules,rules_tool,full
```

Báo cáo có các cột `single/<config>` và `multi/<config>`; file `_details.csv` có thêm cột `mode` và `agents` (agent
nào đã xử lý từng kịch bản).
