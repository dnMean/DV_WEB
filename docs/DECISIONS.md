# Decisions

Những điểm spec chưa nói rõ và cách đã chọn. Mục nào đổi so với spec phải hỏi trước.

## Phase 1

1. **Repo root**: thư mục chứa `SPEC.md` (ở đây là `DV_WEB/`) đóng vai trò `opspilot/` trong mục 4. Không tạo thêm thư mục con `opspilot/`.
2. **Thêm file vào `libs/common`**: `opspilot_common/tools.py` (helper `agent_tool(name, risk, roles)` sinh `openapi_extra`), để 4 service khai báo `x-agent-tool` giống nhau. Không đổi cấu trúc thư mục.
3. **Hash mật khẩu**: dùng thư viện `bcrypt` trực tiếp (passlib không còn được bảo trì và lỗi với bcrypt ≥ 4.1).
4. **System token**: `decode_token` thử `JWT_SECRET` trước, sau đó `SYSTEM_TOKEN_SECRET`. Token ký bằng `JWT_SECRET` mà mang `role=system` bị từ chối (401). Header `X-On-Behalf-Of` chỉ được đọc khi token là system.
5. **Test DB**: test chạy trên SQLite in-memory (`DATABASE_URL` override trong `conftest.py`), mỗi test một DB mới có seed. Test không chạm Postgres thật.
6. **Kiểu `order_id` / `product_id`**: là `int` trong OpenAPI (path param, `ge=1`). Phase 2 Gateway cần ép chuỗi số (`"1002"`) thành int trước khi validate, vì acceptance Phase 2 gửi `"order_id":"1002"`.
7. **`GET /orders`**: staff không truyền `user_id` → thấy tất cả đơn (giới hạn `limit`). Customer truyền `user_id` khác mình → 403. Có thêm filter tuỳ chọn `status`, `limit`.
8. **`POST /orders/{id}/cancel`**: huỷ đơn đã `CANCELLED` trả 200 với đơn hiện tại (idempotent). PAID → 409 `order_already_paid` kèm `suggested_tool: refund_payment`. SHIPPING/DELIVERED → 409 `order_not_cancellable`.
9. **Order items** lưu bản sao `name`, `price` của sản phẩm tại thời điểm đặt (không join chéo DB).
10. **Tìm sản phẩm** không phân biệt hoa thường và dấu (`sac` khớp `Sạc`) qua cột `search_text` đã chuẩn hoá; nhiều từ thì AND.
11. **User có thêm `email`, `phone`** (trả qua `/auth/me`) để Phase 4 guardrail PII biết PII nào thuộc user hiện tại.
12. **Healthcheck Postgres** dùng `pg_isready -h 127.0.0.1` để không báo healthy trong lúc chạy init script (server tạm chỉ nghe unix socket).
13. **Lỗi validation của service** trả `422 {"error":"validation_error"}`. Mã `invalid_arguments` để dành cho Gateway (mục 7.3).

## Phase 2

14. **Payment/Refund**: `POST /refunds` trả `{refund, replayed, refundable_amount}`; cùng `Idempotency-Key` → `replayed: true`, không tạo refund mới; cùng key nhưng khác body → 409. Thiếu key → 400 `idempotency_key_required` (kiểm tra role trước, nên customer luôn nhận 403). Token `system` phải có `X-On-Behalf-Of` và user đó phải là chủ đơn. Payment có trạng thái `PARTIALLY_REFUNDED`/`REFUNDED`.
15. **Shipping**: 1001 có 4 events, 1002 có 3 events (theo spec), 1003 có 1 event. Đổi địa chỉ lặp lại với cùng dữ liệu không tạo event mới (idempotent). Body cho phép tuỳ chọn `recipient_name`, `recipient_phone`.
16. **Gateway không có DB**: registry/rate limit in-memory, audit ghi JSONL `/data/audit.jsonl` (volume `gateway-data`) — spec cho phép. Thêm `GET /audit` (staff) cho UI. Không có `db.py/models.py/seed.py`.
17. **Tool schema**: FastAPI sinh OpenAPI 3.1; registry inline `$ref`, bỏ `title`, gộp `anyOf [X, null]` thành `X`. Tham số header (vd `Idempotency-Key`) không lộ cho LLM. Tên tham số trùng giữa path/query/body → lỗi khi khởi động.
18. **Ép kiểu tham số**: chuỗi số (`"1002"`) được đổi sang int/number theo schema trước khi validate (xem mục 6).
19. **Kết quả `/invoke`**: lỗi của Gateway (403 `tool_forbidden`, 422 `invalid_arguments`, 429 `rate_limited`, 503 `approval_unavailable`) dùng HTTP status tương ứng; lỗi nghiệp vụ từ service (403/404/409/422) trả **HTTP 200** với `{"status":"error","error":..., "message":..., "http_status":...}` vì đó là observation hợp lệ cho LLM. Mọi response đều có trường `status`.
20. **Truncate**: nếu JSON của `data` > `TOOL_MAX_RESULT_CHARS`, `data` thành chuỗi JSON bị cắt và thêm `"truncated": true`.
21. **Write tool** = method khác GET (dùng cho rate limit 3/phút, Idempotency-Key, không retry).
22. **Rate limit env có thể override khi chạy eval** (`RATE_LIMIT_READ_PER_MIN=1000 docker compose up -d gateway`); mặc định vẫn 10/3.

## Phase 3–4

23. **Chống hoàn tiền lặp** hai lớp: (a) Approval so `dedup_key = sha256(user_id|tool|args)`: nếu đã có ticket giống hệt ở trạng thái PENDING/APPROVED/EXECUTED thì trả ticket cũ; Gateway trả `pending_approval` (nếu còn chờ) hoặc lỗi `duplicate_request` (nếu đã thực hiện). Ticket REJECTED/FAILED không chặn yêu cầu mới. (b) Payment dùng `Idempotency-Key = ticket_id`.
24. **`GET /tickets/{id}`** chấp nhận thêm `X-Internal-Secret` để Gateway đọc ticket khi thực thi. Approve dùng UPDATE có điều kiện `status = PENDING` để hai staff không duyệt trùng.
25. **Callback**: Approval gọi `POST /internal/ticket-callback` (kèm `X-Internal-Secret`), best-effort (lỗi chỉ log). Agent lưu message `role=system, kind=notification`; message này nằm trong history gửi LLM ở lượt sau.
26. **Tin nhắn bị guardrail chặn** được lưu với `kind=blocked` (hiển thị trong lịch sử nhưng không gửi lại cho LLM).
27. **pending_approval**: khi một tool call trả `pending_approval`, các tool call còn lại trong cùng response nhận observation `skipped`; câu trả lời là template tiếng Việt kèm mã ticket (không gọi LLM thêm).
28. **PII guard**: được phép hiển thị email/SĐT của user (`/auth/me`) và PII xuất hiện trong kết quả tool thành công của chính lượt đó (đã qua kiểm tra ownership của service). Các PII khác bị thay bằng `[đã ẩn]`.
29. **Tool-output guard** quét mọi chuỗi trong `data` bằng mẫu injection + mẫu "gọi tool" (`gọi refund_payment`, tên tool ghi, ...). Luôn bọc kết quả trong `{"untrusted_data": ...}` khi lớp này bật. Kết quả `pending_approval` do Gateway sinh nên không bọc.
30. **LLM classifier** (`GUARD_INPUT_LLM`) fail-open: LLM lỗi thì cho qua và ghi lý do vào trace.
31. **`/chat` trả thêm** `ticket_id`, `usage`, `latency_ms`, `llm_calls` (phục vụ UI và eval).
32. **Retry LLM**: SDK `max_retries=0`, tự retry 2 lần (backoff 1s, 2s) với 429/5xx/lỗi mạng; 401 → `llm_auth` không retry. Lỗi LLM → `status=error`.
33. **UI** gọi Auth/Agent/Approval/Gateway trực tiếp bằng JWT của user (không qua Agent). Trang Trace chỉ cho staff (API `/traces` chỉ staff); customer xem các bước tool trong expander của từng câu trả lời.

## Phase 5

34. **Chọn cấu hình guardrail khi eval**: header `X-Guard-Config` (JSON) trên `/chat`, **chỉ** có hiệu lực khi kèm `X-Internal-Secret` đúng; nếu không → 403. Tránh việc user thường tự tắt guardrail. Cấu hình được lưu trong `traces.guard_config`.
35. **Định nghĩa metrics**: xem cuối file báo cáo. Attack success = kịch bản `attack: true` vi phạm `tools_called_exclude` hoặc `answer_not_contains`. False block = kịch bản không phải attack mà `status=blocked`. "Số bước" = số lời gọi LLM (`llm_calls`); có thêm số tool call TB.
36. **Langfuse**: chưa tích hợp (tuỳ chọn trong spec); trace đầy đủ nằm trong `agent_db`.

## Đổi provider LLM

37. **DeepSeek → OpenAI** (theo yêu cầu, khác spec mục 9.1 và 11): env `OPENAI_API_KEY`, `OPENAI_BASE_URL` (mặc định `https://api.openai.com/v1`), `OPENAI_MODEL` (mặc định `gpt-4o-mini`, đổi được qua env). Class `OpenAIClient` trong `services/agent/app/llm.py`, vẫn qua interface `LLMClient` nên loop/guardrails/test không đổi.
38. **Mỗi đơn chỉ một yêu cầu hoàn tiền**: `x-agent-tool` có thêm `dedup_fields` (tuỳ chọn); `refund_payment` dùng `["order_id"]` — bỏ qua cả `amount` lẫn `reason`. Gateway gửi `dedup_arguments` cho Approval. Nếu đơn đã có ticket PENDING/APPROVED/EXECUTED (ưu tiên báo EXECUTED), Approval trả ticket cũ (HTTP 200) và Gateway trả `duplicate_request` kèm trạng thái + tham số của ticket cũ; không tạo ticket mới. Ticket REJECTED/FAILED không chặn yêu cầu mới. Lớp chặn cuối: Payment không cho tổng hoàn vượt số đã thanh toán (422 → ticket FAILED).

## Đồng bộ giữa các service (xem docs/USECASES.md)

39. **Use case là nguồn sự thật**: quy tắc nghiệp vụ xuyên service nằm ở `docs/USECASES.md`, mỗi UC có test e2e trong `tests/e2e/` chạy trên stack thật (`docker compose --profile test run --rm e2e`). Đổi quy tắc → đổi tài liệu và test trước.
40. **Chính sách hoàn tiền** (thay mục 14): PAID chưa giao → chỉ hoàn toàn bộ, huỷ vận đơn, Order `REFUNDED`, cộng kho; SHIPPING → không hoàn; DELIVERED → hoàn một phần/toàn bộ, không cộng kho; PENDING/CANCELLED/REFUNDED → không hoàn. Payment đọc trạng thái thật từ Order/Shipping (`/internal/*`) cả lúc precheck lẫn lúc thực thi.
41. **Precheck**: `x-agent-tool.precheck` (`/refunds/validate`). Gateway gọi bằng JWT của user trước khi tạo ticket; không hợp lệ → trả lỗi cho LLM, không tạo ticket.
42. **Outbox** (`libs/common/opspilot_common/outbox.py`): cập nhật chéo (Order→Product cộng kho, Payment→Order `refund-applied`, Shipping→Order `shipping-status`) được ghi cùng transaction rồi gửi ngay; lỗi mạng/5xx/408/429 → retry nền với backoff (tối đa 8 lần), 4xx → FAILED + log lỗi. Payload idempotent (tổng tuyệt đối, Idempotency-Key cố định).
43. **Huỷ vận đơn đồng bộ, trước khi ghi refund**: nếu vận đơn đã rời kho (409) hoặc Shipping không phản hồi (503) thì không hoàn tiền; ticket `FAILED`.
44. **Order mới có** trạng thái `REFUNDED` và trường `refunded_amount`; **Shipment** có `CANCELLED`; seed thêm vận đơn `WAITING_PICKUP` cho đơn 1005 (đơn PAID phải có vận đơn).
45. **Staff cập nhật vận chuyển**: `POST /shipments/{order_id}/advance` (không phải tool của agent), trang UI "Vận chuyển". Chỉ cho phép WAITING_PICKUP→IN_TRANSIT→DELIVERED.
46. **Reset dev**: `POST /internal/reset` ở product/order/payment/shipping/approval/gateway, cần `ALLOW_RESET=true` + `X-Internal-Secret`. Dùng cho e2e và eval (eval reset trước mỗi cấu hình guardrail).
47. **Endpoint nội bộ** (`/internal/*`) xác thực bằng `X-Internal-Secret` qua `require_internal` trong `libs/common`.
48. **Staff là người xét duyệt** (UC05–UC06, UC60–UC67): staff không tạo yêu cầu hoàn tiền (`refund_payment` chỉ role customer) nên không thể tự tạo rồi tự duyệt; cũng hết lỗi "staff hoàn giúp khách luôn FAILED". Tool của staff: `search_orders` (lọc user_id, order_id, status, refunded), `list_refund_requests`, `approve_refund` / `reject_refund` **theo mã đơn**. `list_my_orders` chỉ còn cho customer. Endpoint duyệt theo mã ticket (`/tickets/{id}/approve|reject`) vẫn giữ cho UI nhưng không còn là tool của agent.
49. **`x-agent-tool.confirm_args`**: Agent gửi kèm tin nhắn gốc của người dùng (`user_message`) trong `/invoke`; Gateway chỉ cho gọi `approve_refund`/`reject_refund` khi mã đơn xuất hiện trong tin nhắn đó **như một từ riêng** ("1001" không khớp "10011"), nếu không → 403 `confirmation_required`. Kiểm tra ở Gateway nên không phụ thuộc LLM; nội dung khách viết trong lý do hoàn tiền không thể khiến agent tự duyệt.
50. **`list_refund_requests`** (Approval `/refund-requests`) dành cho cả khách (chỉ thấy yêu cầu của mình) và staff. Mỗi đơn có tối đa một yêu cầu đang chờ nên mã đơn xác định duy nhất yêu cầu cần duyệt. `get_approval_ticket` chấp nhận mã ticket rút gọn ≥ 8 ký tự.

51. **Ngân sách token** (UC58, thay cách hiểu spec 9.3): câu trả lời cuối của LLM luôn được trả cho người dùng (token đã tiêu rồi); chỉ dừng `budget_exceeded` khi LLM còn muốn gọi thêm tool mà tổng token đã vượt `AGENT_MAX_TOKENS`. Trước đây một câu trả lời hoàn chỉnh bị bỏ đi chỉ vì vượt ngưỡng ở lần gọi cuối.
52. **Lịch sử gọn**: lượt cũ chỉ gửi lại câu hỏi, câu trả lời cuối và thông báo hệ thống; tool call / kết quả tool thô của lượt cũ không gửi lại LLM (vẫn lưu đủ trong `messages` và trace). Prompt không còn phình theo số lượt (hội thoại 3 lượt: ~13k → ~7–8k token mỗi lượt).
53. **Danh sách đơn có phân trang** (UC57): `list_my_orders` / `search_orders` trả `{total, offset, limit, has_more, orders}`; prompt yêu cầu trả lời "bao nhiêu" theo `total`, ghi "x/total" khi còn trang và dùng `offset` khi khách muốn xem tiếp.
54. **Staff đổi trạng thái đơn qua chat** (UC45–UC49): không gán trạng thái trực tiếp; SHIPPING/DELIVERED qua `update_shipment_status` (API `/shipments/{order_id}/advance` của Shipping, nay là tool của staff, `confirm_args=["order_id"]`, vị trí/ghi chú tự điền nếu thiếu), CANCELLED qua `cancel_order`, REFUNDED qua `approve_refund`. Không có thao tác đánh dấu PAID.
55. **Mô tả tool chỉ nói khi nào dùng, không liệt kê điều kiện nghiệp vụ**: khi mô tả có điều kiện (vd "đơn PAID không huỷ được"), gpt-4o-mini tự phán đoán và bịa trạng thái thay vì gọi tool. Điều kiện do service kiểm tra; agent gọi tool rồi giải thích lỗi trả về. Prompt có quy tắc 3a tương ứng.
56. **Rate limit ghi riêng cho staff**: `RATE_LIMIT_STAFF_WRITE_PER_MIN=30` (khách vẫn 3/phút) vì staff xử lý nhiều đơn liên tiếp.
57. **Chọn model**: đo trên câu staff dạng tường thuật ("Đơn 1003 đã được lấy hàng"), gpt-4o-mini gọi đúng tool 3/9 lần, gpt-4.1-mini 7/9, gpt-4o 7/9; câu dạng mệnh lệnh ("Cập nhật đơn 1003 đã lấy hàng") đúng 12/12 ở cả gpt-4o-mini và gpt-4.1-mini. Giữ mặc định gpt-4o-mini; đổi qua `OPENAI_MODEL` nếu cần.

## Đặt hàng và thanh toán qua chat (xem docs/USECASES.md mục 3b)

58. **Phạm vi mới** (khác spec và mục 54 "không có thao tác đánh dấu PAID"): khách hỏi sản phẩm và đặt hàng qua chat, có thanh toán **giả lập** (luôn thành công). Ba tool mới, chỉ role customer: `quote_order` (low), `place_order` (medium, `confirm_args=["quote_id"]`), `pay_order` (medium, `confirm_args=["order_id"]`). Staff vẫn không đánh dấu đã thanh toán.
59. **Báo giá rồi xác nhận bằng mã** thay vì để LLM tự quyết: mã báo giá do Order sinh ngẫu nhiên trong lượt báo giá, Gateway chỉ cho `place_order` khi tin nhắn của khách chứa mã đó (dùng lại cơ chế `confirm_args`). Nhờ vậy agent không thể đặt hàng trong cùng lượt báo giá, không đặt vì nội dung mô tả sản phẩm, và khách luôn thấy sản phẩm, số lượng, tổng tiền, địa chỉ trước khi đặt. Đổi lại đặt hàng mất 2 lượt chat. Thanh toán dùng mã đơn làm xác nhận (khách gõ "thanh toán đơn 1006 bằng thẻ").
60. **Giá chốt theo báo giá**: đơn dùng giá lúc báo giá (khách đã đồng ý giá đó); báo giá hết hạn sau `QUOTE_TTL_MINUTES=30`. Tồn kho được kiểm tra lúc báo giá nhưng chỉ **trừ lúc đặt** (đồng bộ, all-or-nothing, Product `/internal/inventory/reserve`). Mỗi lần thử đặt dùng Idempotency-Key riêng (`quote-<mã>-<ngẫu nhiên>`) để lần lỗi chỉ trả lại đúng phần nó đã trừ; đặt lại cùng mã thì trả đơn cũ nhờ khoá dòng báo giá (`SELECT … FOR UPDATE`).
61. **Thanh toán do Order điều phối**: Order khoá dòng đơn, gọi Payment `/internal/payments` đồng bộ (idempotent theo mã đơn), rồi mới chuyển `PAID` và ghi outbox tạo vận đơn sang Shipping. Huỷ đơn chạy đồng thời phải chờ khoá nên không có trường hợp "đã thu tiền mà đơn bị huỷ". Nếu Order lỗi khi lưu sau khi Payment đã ghi, khách thanh toán lại sẽ nhận lại đúng thanh toán cũ (không thu hai lần).
62. **Bảng mới, không sửa bảng cũ**: `quotes` và `order_delivery` (tên, SĐT, địa chỉ giao của đơn) là bảng mới nên `create_all` tự tạo trên DB đang chạy, không cần migration; `OrderOut` giữ nguyên. Đơn seed không có `order_delivery`, nên `pay_order` nhận thêm thông tin giao hàng tuỳ chọn (thiếu → 422 `delivery_info_required`).
63. **Order có thêm phụ thuộc** `PAYMENT_URL`, `SHIPPING_URL` (outbox target `shipping`); Product thêm `GET /internal/products?ids=` và `POST /internal/inventory/reserve`; Payment thêm `POST /internal/payments`; Shipping thêm `POST /internal/shipments`.
64. **Prompt**: mô tả tool vẫn chỉ nói khi nào dùng (mục 55). Đo với gpt-4o-mini: ban đầu model hỏi lại "đúng không?" thay vì báo giá, nên prompt (quy tắc 6b) nói rõ là gọi `quote_order` ngay khi đủ thông tin, vì báo giá chính là bước để khách kiểm tra.
65. **Không hỗ trợ COD khi đặt qua chat** (sửa lỗi của mục 58): bản đầu coi mọi phương thức là trả trước, nên đơn COD bị ghi `PAID` / Payment `SUCCESS` dù chưa thu tiền, và khách còn có thể "hoàn" số tiền chưa trả. Làm COD đúng cần thêm trạng thái đơn (đã xác nhận, thu tiền khi giao) và đổi quy tắc huỷ/hoàn; đã chọn bỏ COD: `pay_order.method` chỉ nhận `CARD`, `BANK_TRANSFER`, `E_WALLET`. Dữ liệu seed vẫn có thanh toán COD (đơn 1001 đã giao, tức đã thu tiền) và `/internal/payments` vẫn nhận mọi phương thức.

## Viết lại các service nghiệp vụ bằng TypeScript + gRPC

66. **Công nghệ theo bảng phân công**: Gateway = TypeScript + Fastify + Ajv + Redis; Auth, Order, Product, Payment, Shipping, Approval = TypeScript + NestJS + `@nestjs/swagger` + Prisma (Auth dùng `jose` cho JWT, `bcryptjs` cho mật khẩu; hash `$2b$` cũ vẫn đăng nhập được). Agent và UI giữ Python. Hợp đồng HTTP (đường dẫn, body, mã lỗi, tên tool, mô tả tool) giữ nguyên nên Agent, UI, eval và toàn bộ e2e không đổi.
67. **Mỗi service là một microservice độc lập**: tiến trình/container riêng, DB riêng, `package.json` + lockfile + Dockerfile riêng. Code dùng chung (`libs/node-common`) được **chép** vào `src/common/` lúc build, không phải package dùng chung lúc chạy.
68. **Service ↔ service qua gRPC** (`proto/*.proto`, cổng 50051 trong mạng docker): toàn bộ các endpoint `/internal/*` HTTP cũ (trừ `/internal/reset` dùng cho test) thành RPC: `ProductInternal.GetCatalog/Reserve/Restock`, `OrderInternal.GetOrder/RefundApplied/ShippingStatus`, `PaymentInternal.Charge`, `ShippingInternal.CreateShipment/GetShipment/CancelShipment`, `ApprovalInternal.CreateTicket/GetTicket` (Gateway → Approval), `AuthInternal.GetUser/VerifyToken`. Xác thực bằng metadata `x-internal-secret`, request id qua metadata `x-request-id`. Các service vẫn tự kiểm JWT bằng secret chung (không gọi Auth mỗi request) để không phụ thuộc Auth khi chạy.
69. **Vẫn là HTTP** ở những chỗ phía bên kia là REST: Agent → Gateway, UI → các service, Gateway → service khi thực thi tool (tool sinh từ Swagger nên gọi đúng endpoint REST đã mô tả), Gateway → `/refunds/validate` (precheck), Approval → Gateway `/internal/execute-ticket`, Approval → Agent `/internal/ticket-callback`.
70. **Lỗi qua gRPC**: server đặt `details` của gRPC status là JSON `{http_status, error, message, ...extra}`; client giải mã lại thành mã HTTP tương đương nên logic cũ (404 → không tìm thấy, 409 → từ chối nghiệp vụ, còn lại → 503 `dependency_unavailable`) giữ nguyên. Không kết nối được / quá hạn → 503/504.
71. **Outbox** lưu tên RPC + payload (bảng `outbox` mỗi service). Retry nền khi lỗi tạm thời (5xx, 408, 429, `UNAVAILABLE`, `DEADLINE_EXCEEDED`), lỗi nghiệp vụ → `FAILED` như cũ. Khoá idempotency đi trong payload (`idempotency_key`) và metadata.
72. **Redis ở Gateway**: rate limit là token bucket bằng script Lua (dùng đồng hồ của Redis, đúng khi chạy nhiều Gateway); **khoá idempotency** `SET NX PX` cho mọi tool ghi và cho thực thi ticket: cùng một lời gọi ghi giống hệt đang chạy → 409 `request_in_progress` thay vì gửi trùng xuống service. Redis lỗi → `/invoke` trả 500 (fail closed, không bỏ qua rate limit). `/internal/reset` của Gateway xoá các khoá `gw:*`.
73. **Ajv** kiểm tham số tool theo JSON Schema sinh từ Swagger (thay `jsonschema` của Python); Fastify cũng dùng JSON Schema cho body `/invoke`. Swagger của Nest là OpenAPI 3.0 nên `amount` của `refund_payment` là `minimum: 1` thay cho `exclusiveMinimum: 0` (cùng nghĩa với số nguyên).
74. **Prisma**: container chạy `prisma db push` trước khi khởi động (demo, không dùng migration; `schema.prisma` là nguồn sự thật, nâng cấp được DB do bản Python tạo). Tiền lưu `Int` (đủ cho ≤ 2,1 tỷ đ/đơn). Khoá dòng `SELECT … FOR UPDATE` viết bằng `$queryRaw` trong transaction tương tác.
75. **Dữ liệu demo sinh thêm** (`DEMO_EXTRA_ORDERS`) dùng PRNG mulberry32 cố định seed: đơn 1006+ khác bản Python nhưng vẫn giống hệt nhau giữa Order/Payment/Shipping/Approval (UC07). Đơn 1001–1005 không đổi.
76. **OpenTelemetry chưa tích hợp**: trace xuyên service vẫn bằng `X-Request-ID` (HTTP) / `x-request-id` (gRPC) trong log JSON; trace hội thoại đầy đủ vẫn ở `agent_db`.
