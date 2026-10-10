# node-common

Code dùng chung cho các service TypeScript (Auth, Order, Product, Payment, Shipping, Approval, Gateway).

Không phải package npm: script `sync-common` của mỗi service chép `src/` vào `services/<name>/src/common/`
(thư mục sinh ra, không commit) trước khi build, nên mỗi service vẫn build và chạy độc lập.

- `src/*.ts`: không phụ thuộc framework (env, lỗi, log JSON + request id, JWT bằng `jose`, gRPC, outbox, dữ liệu demo).
- `src/nest/*.ts`: phần riêng cho NestJS (guard, filter, pipe, `@AgentTool`, bootstrap HTTP + gRPC). Gateway (Fastify) không dùng.
