import Fastify, { FastifyError, FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';

import { AuditLog } from './audit';
import {
  CurrentUser, INTERNAL_SECRET_HEADER, ON_BEHALF_OF_HEADER, createSystemToken, isInternalSecret, isStaff, userFromHeaders,
} from './common/auth';
import { envBool } from './common/env';
import { AppError, DEFAULT_CODES, errorBody } from './common/errors';
import { GrpcClient, RpcCallError } from './common/grpc';
import { REQUEST_ID_HEADER, forwardHeaders, getRequestId, log, runWithRequestId } from './common/logging';
import { config } from './config';
import * as invoker from './invoker';
import { GatewayState } from './redis';
import { Registry, ToolSpec, isWrite, toOpenAI } from './registry';

type Json = Record<string, unknown>;

interface InvokeBody {
  tool: string;
  arguments: Json;
  conversation_id: string;
  user_message: string; // the end user's own message for this turn (sent by the agent); used for confirm_args
}

interface ApprovalTicket {
  id: string;
  user_id: number;
  tool: string;
  arguments_json: string;
  status: string;
  result_json: string;
}

const INVOKE_SCHEMA = {
  body: {
    type: 'object',
    required: ['tool'],
    additionalProperties: false,
    properties: {
      tool: { type: 'string', minLength: 1, maxLength: 100 },
      arguments: { type: 'object', default: {} },
      conversation_id: { type: 'string', maxLength: 100, default: '' },
      user_message: { type: 'string', maxLength: 4000, default: '' },
    },
  },
};

const EXISTING_STATE: Record<string, string> = {
  PENDING: 'đang chờ nhân viên duyệt',
  APPROVED: 'đã được duyệt, đang thực hiện',
  EXECUTED: 'đã được duyệt và thực hiện',
};

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export interface Deps {
  registry: Registry;
  state: GatewayState;
  audit: AuditLog;
  approval: GrpcClient;
}

export function buildApp(deps: Deps): FastifyInstance {
  const { registry, state, audit, approval } = deps;
  const app = Fastify({ logger: false, bodyLimit: 1_000_000 });

  // ---- request id, access log, uniform errors ------------------------------------------------
  app.addHook('onRequest', (req, reply, done) => {
    runWithRequestId(req.headers[REQUEST_ID_HEADER] as string | undefined, () => {
      reply.header('X-Request-ID', getRequestId());
      done();
    });
  });
  app.addHook('onResponse', (req, reply, done) => {
    if (req.url !== '/health') {
      log.info(`${req.method} ${req.url.split('?')[0]} ${reply.statusCode} ${reply.elapsedTime.toFixed(1)}ms`);
    }
    done();
  });
  app.setErrorHandler((err: FastifyError | AppError, _req, reply) => {
    if (err instanceof AppError) return reply.status(err.status).send(err.body());
    if ((err as FastifyError).validation) {
      return reply.status(422).send(errorBody('validation_error', err.message));
    }
    const status = (err as FastifyError).statusCode ?? 500;
    if (status >= 500) log.error(`unhandled error: ${err.message}`, err);
    return reply.status(status).send(errorBody(DEFAULT_CODES[status] ?? 'error', status >= 500 ? 'Lỗi hệ thống' : err.message));
  });
  app.setNotFoundHandler((req, reply) => reply.status(404).send(errorBody('not_found', `Not Found: ${req.method} ${req.url}`)));

  const authenticate = async (req: FastifyRequest, roles?: string[]): Promise<CurrentUser> => {
    const user = await userFromHeaders(req.headers.authorization, req.headers[ON_BEHALF_OF_HEADER] as string | undefined);
    if (!user) throw new AppError(401, 'unauthorized', 'Thiếu token xác thực');
    if (roles && !roles.includes(user.role)) {
      throw new AppError(403, 'forbidden', `Role '${user.role}' không có quyền thực hiện thao tác này`);
    }
    return user;
  };
  const requireInternal = (req: FastifyRequest) => {
    if (!isInternalSecret(req.headers[INTERNAL_SECRET_HEADER] as string | undefined)) {
      throw new AppError(403, 'forbidden', 'Sai hoặc thiếu X-Internal-Secret');
    }
  };

  // ---- routes --------------------------------------------------------------------------------
  app.get('/health', async () => ({ status: 'ok' }));

  app.get('/tools', async (req) => {
    const user = await authenticate(req);
    return registry.forRole(user.role).map(toOpenAI);
  });

  app.get('/tools/meta', async (req) => {
    await authenticate(req, ['staff']);
    return registry.all();
  });

  app.get<{ Querystring: { limit: number } }>('/audit', {
    schema: { querystring: { type: 'object', properties: { limit: { type: 'integer', minimum: 1, maximum: 500, default: 50 } } } },
  }, async (req) => {
    await authenticate(req, ['staff']);
    return audit.tail(req.query.limit);
  });

  async function createTicket(user: CurrentUser, spec: ToolSpec, args: Json, conversationId: string): Promise<[number, invoker.Result]> {
    const dedup = spec.dedup_fields ? Object.fromEntries(spec.dedup_fields.map((k) => [k, args[k] ?? null])) : args;
    let reply: { created: boolean; ticket: ApprovalTicket };
    try {
      reply = await approval.call('CreateTicket', {
        conversation_id: conversationId, user_id: user.id, tool: spec.name,
        arguments_json: JSON.stringify(args), dedup_arguments_json: JSON.stringify(dedup),
      }, { timeoutMs: config.toolTimeoutMs });
    } catch (exc) {
      log.error(`cannot create approval ticket: ${String(exc)}`);
      return [503, invoker.error('approval_unavailable', 'Không tạo được yêu cầu duyệt, vui lòng thử lại sau')];
    }
    const { ticket } = reply;
    if (!reply.created) { // Approval returned an existing ticket for the same request
      const state = EXISTING_STATE[ticket.status] ?? ticket.status;
      const existing = JSON.parse(ticket.arguments_json);
      return [200, invoker.error('duplicate_request',
        `Đã có yêu cầu ${spec.name} cho cùng đối tượng ${state} (ticket ${ticket.id}, `
        + `tham số ${JSON.stringify(existing)}). Yêu cầu mới bị từ chối, không tạo ticket mới.`,
        { ticket_id: ticket.id, existing_status: ticket.status, existing_arguments: existing })];
    }
    return [200, {
      status: 'pending_approval', ticket_id: ticket.id,
      message: 'Thao tác rủi ro cao: đã tạo yêu cầu, đang chờ nhân viên duyệt.',
    }];
  }

  async function invoke(body: InvokeBody, user: CurrentUser): Promise<[number, invoker.Result]> {
    const spec = registry.get(body.tool);
    // 1. existence + role
    if (!spec || !spec.roles.includes(user.role)) {
      return [403, invoker.error('tool_forbidden', `Tool '${body.tool}' không tồn tại hoặc bạn không có quyền dùng`)];
    }

    // 2. JSON Schema validation (Ajv)
    const args = invoker.coerceArguments(spec, body.arguments);
    const problem = invoker.validateArguments(spec, args);
    if (problem) return [422, invoker.error('invalid_arguments', problem)];

    // 2b. confirmation: some arguments must come from the user's own words, not from the LLM
    for (const arg of spec.confirm_args ?? []) {
      const value = String(args[arg] ?? '').trim();
      const typed = value && new RegExp(`(?<![0-9A-Za-z])${escapeRegExp(value)}(?![0-9A-Za-z])`, 'i').test(body.user_message);
      if (!typed) {
        return [403, invoker.error('confirmation_required',
          `Để dùng '${spec.name}', người dùng phải tự gõ ${arg} '${args[arg] ?? ''}' trong tin nhắn `
          + 'của mình. Hãy hỏi người dùng xác nhận bằng cách nhập mã đó.')];
      }
    }

    // 3. rate limit per (user, tool), shared through Redis
    const perMinute = !isWrite(spec) ? config.rateLimitReadPerMin
      : isStaff(user) ? config.rateLimitStaffWritePerMin : config.rateLimitWritePerMin;
    const [allowed, retryAfter] = await state.allow(user.id, spec.name, perMinute);
    if (!allowed) {
      return [429, invoker.error('rate_limited',
        `Gọi '${spec.name}' quá ${perMinute} lần/phút, thử lại sau ${Math.round(retryAfter)}s`,
        { retry_after: Math.round(retryAfter * 10) / 10 })];
    }

    const userHeaders = { Authorization: `Bearer ${user.token}`, ...forwardHeaders() };
    // 4. high risk -> precheck on the service, then an approval ticket; the action itself is NOT executed
    if (spec.risk === 'high') {
      if (spec.precheck) {
        const rejected = await invoker.precheck(spec, args, userHeaders, config.toolTimeoutMs);
        if (rejected) return [200, rejected];
      }
      return createTicket(user, spec, args, body.conversation_id);
    }

    // 5-7. forward to the service; identical concurrent writes are refused by the idempotency lock
    if (!isWrite(spec)) {
      return [200, await invoker.callService(spec, args, userHeaders, config.toolTimeoutMs, config.toolMaxResultChars)];
    }
    const key = invoker.idempotencyKey(user.id, spec.name, args, body.conversation_id);
    const release = await state.lock(key, config.toolTimeoutMs * 2 + 5000);
    if (!release) {
      return [409, invoker.error('request_in_progress',
        `Yêu cầu '${spec.name}' giống hệt đang được xử lý, hãy chờ kết quả thay vì gửi lại.`)];
    }
    try {
      return [200, await invoker.callService(spec, args, { ...userHeaders, 'Idempotency-Key': key },
        config.toolTimeoutMs, config.toolMaxResultChars)];
    } finally {
      await release();
    }
  }

  app.post<{ Body: InvokeBody }>('/invoke', { schema: INVOKE_SCHEMA }, async (req, reply) => {
    const user = await authenticate(req);
    const started = performance.now();
    const [status, result] = await invoke(req.body, user);
    audit.write({
      request_id: getRequestId(), user_id: user.id, tool: req.body.tool, arguments: req.body.arguments,
      status: result.status, error: result.error ?? null, latency_ms: Math.round((performance.now() - started) * 10) / 10,
      conversation_id: req.body.conversation_id, ticket_id: result.ticket_id ?? null,
    });
    return reply.status(status).send(result);
  });

  /** Approval -> Gateway: execute an approved ticket with a system token on behalf of the customer. */
  app.post<{ Params: { ticket_id: string } }>('/internal/execute-ticket/:ticket_id', async (req) => {
    requireInternal(req);
    const started = performance.now();
    const ticketId = req.params.ticket_id;
    let ticket: ApprovalTicket;
    try {
      ticket = await approval.call<ApprovalTicket>('GetTicket', { ticket_id: ticketId });
    } catch (exc) {
      if (exc instanceof RpcCallError && exc.status === 404) throw new AppError(404, 'ticket_not_found', `Không tìm thấy ticket ${ticketId}`);
      throw new AppError(503, 'approval_unavailable', 'Không đọc được ticket từ Approval');
    }
    if (ticket.status !== 'APPROVED' || ticket.result_json) {
      throw new AppError(409, 'ticket_not_executable', `Ticket đang ở trạng thái ${ticket.status}`);
    }
    const ticketArgs = JSON.parse(ticket.arguments_json) as Json;
    const spec = registry.get(ticket.tool);
    let result: invoker.Result;
    if (!spec) {
      result = invoker.error('tool_not_found', `Tool '${ticket.tool}' không còn trong registry`);
    } else {
      const args = invoker.coerceArguments(spec, ticketArgs);
      const problem = invoker.validateArguments(spec, args);
      const release = problem ? null : await state.lock(ticket.id, config.toolTimeoutMs * 2 + 5000);
      if (problem) {
        result = invoker.error('invalid_arguments', problem);
      } else if (!release) {
        result = invoker.error('request_in_progress', `Ticket ${ticket.id} đang được thực hiện`);
      } else {
        try {
          const headers = {
            Authorization: `Bearer ${await createSystemToken()}`,
            'X-On-Behalf-Of': String(ticket.user_id),
            'Idempotency-Key': ticket.id,
            ...forwardHeaders(),
          };
          result = await invoker.callService(spec, args, headers, config.toolTimeoutMs, config.toolMaxResultChars);
        } finally {
          await release();
        }
      }
    }
    audit.write({
      request_id: getRequestId(), user_id: ticket.user_id, tool: ticket.tool, arguments: ticketArgs,
      status: result.status, error: result.error ?? null, latency_ms: Math.round((performance.now() - started) * 10) / 10,
      ticket_id: ticket.id, via: 'system',
    });
    return result;
  });

  /** Dev only: forget rate limit buckets and locks (e2e tests, eval). */
  app.post('/internal/reset', async (req, reply: FastifyReply) => {
    requireInternal(req);
    if (!envBool('ALLOW_RESET', false)) throw new AppError(403, 'reset_disabled', 'ALLOW_RESET chưa bật');
    await state.reset();
    return reply.send({ status: 'reset', extra_orders: 0 });
  });

  return app;
}
