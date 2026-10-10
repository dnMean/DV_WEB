import { createHash } from 'node:crypto';

import { Injectable } from '@nestjs/common';
import { Prisma, Ticket } from '@prisma/client';

import { AppError, CurrentUser, env, envNumber, forwardHeaders, log } from './common';
import { RefundRequestOut, TicketOut } from './dto';
import { PrismaService } from './prisma.service';

export const REFUND_TOOL = 'refund_payment';
// A new identical request while one of these exists returns the existing ticket (no second refund).
const DEDUP_STATUSES = ['PENDING', 'APPROVED', 'EXECUTED'];

type Json = Record<string, unknown>;

/** JSON with sorted keys, so equal arguments always hash the same. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical((value as Json)[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export function dedupKey(userId: number, tool: string, args: Json): string {
  return createHash('sha256').update(`${userId}|${tool}|${canonical(args)}`).digest('hex');
}

export function ticketOut(t: Ticket): TicketOut {
  return {
    id: t.id, conversation_id: t.conversationId, user_id: t.userId, tool: t.tool, arguments: t.arguments as Json,
    status: t.status, reviewer_id: t.reviewerId, review_note: t.reviewNote, result: (t.result as Json | null) ?? null,
    created_at: t.createdAt.toISOString(), updated_at: t.updatedAt.toISOString(),
  };
}

export function refundRequestOut(t: Ticket): RefundRequestOut {
  const args = t.arguments as Json;
  const result = (t.result ?? {}) as Json;
  return {
    ticket_id: t.id, order_id: (args.order_id as number) ?? null, user_id: t.userId, amount: (args.amount as number) ?? null,
    reason: String(args.reason ?? ''), status: t.status, review_note: t.reviewNote,
    failure: t.status === 'FAILED' ? String(result.message || result.error || '') || null : null,
    created_at: t.createdAt.toISOString(), updated_at: t.updatedAt.toISOString(),
  };
}

@Injectable()
export class TicketsService {
  constructor(private readonly db: PrismaService) {}

  /** gRPC CreateTicket (Gateway). Returns the existing ticket when an identical request is pending/executed. */
  async create(req: { conversation_id: string; user_id: number; tool: string; arguments: Json; dedup_arguments: Json | null }) {
    if (!req.tool || req.tool.length > 100 || !(req.user_id > 0)) {
      throw new AppError(422, 'validation_error', 'tool và user_id là bắt buộc');
    }
    const key = dedupKey(req.user_id, req.tool, req.dedup_arguments ?? req.arguments);
    const matches = await this.db.ticket.findMany({
      where: { dedupKey: key, status: { in: DEDUP_STATUSES } }, orderBy: { createdAt: 'desc' },
    });
    // an already executed identical request wins over a pending one
    const existing = matches.find((t) => t.status === 'EXECUTED') ?? matches[0];
    if (existing) {
      log.info(`duplicate request for ticket ${existing.id} (${existing.status})`);
      return { created: false, ticket: existing };
    }
    const ticket = await this.db.ticket.create({
      data: {
        conversationId: req.conversation_id.slice(0, 100), userId: req.user_id, tool: req.tool,
        arguments: req.arguments as Prisma.InputJsonValue, dedupKey: key,
      },
    });
    log.info(`ticket ${ticket.id} created: user=${req.user_id} tool=${req.tool}`);
    return { created: true, ticket };
  }

  /** Accepts a full id or a unique prefix of at least 8 characters. */
  async get(ticketId: string): Promise<Ticket> {
    const id = ticketId.toLowerCase();
    let ticket: Ticket | null;
    if (id.length === 36) {
      ticket = await this.db.ticket.findUnique({ where: { id } });
    } else {
      const matches = await this.db.ticket.findMany({ where: { id: { startsWith: id } }, take: 2 });
      if (matches.length > 1) {
        throw new AppError(409, 'ticket_id_ambiguous', `Có nhiều ticket bắt đầu bằng ${id}, hãy nhập đủ mã`);
      }
      ticket = matches[0] ?? null;
    }
    if (!ticket) throw new AppError(404, 'ticket_not_found', `Không tìm thấy ticket ${id}`);
    return ticket;
  }

  async getFor(ticketId: string, user: CurrentUser): Promise<Ticket> {
    const ticket = await this.get(ticketId);
    if (user.role !== 'staff' && ticket.userId !== user.id) {
      throw new AppError(403, 'forbidden', 'Bạn không có quyền xem ticket này');
    }
    return ticket;
  }

  list(status: string | undefined, limit: number): Promise<Ticket[]> {
    return this.db.ticket.findMany({ where: status ? { status } : {}, orderBy: { createdAt: 'desc' }, take: limit });
  }

  refundRequests(filter: { status?: string; orderId?: number; userId?: number }, limit: number): Promise<Ticket[]> {
    return this.db.ticket.findMany({
      where: {
        tool: REFUND_TOOL,
        ...(filter.status ? { status: filter.status } : {}),
        ...(filter.userId ? { userId: filter.userId } : {}),
        ...(filter.orderId ? { arguments: { path: ['order_id'], equals: filter.orderId } } : {}),
      },
      orderBy: { createdAt: 'desc' },
      take: limit,
    });
  }

  async pendingRefundFor(orderId: number): Promise<Ticket> {
    const [ticket] = await this.refundRequests({ status: 'PENDING', orderId }, 1);
    if (!ticket) {
      throw new AppError(404, 'refund_request_not_found', `Đơn ${orderId} không có yêu cầu hoàn tiền nào đang chờ duyệt`);
    }
    return ticket;
  }

  /** Atomically move PENDING -> status so two reviewers cannot both act on one ticket. */
  private async claim(ticketId: string, status: 'APPROVED' | 'REJECTED', reviewer: CurrentUser, note: string) {
    const ticket = await this.get(ticketId);
    const { count } = await this.db.ticket.updateMany({
      where: { id: ticket.id, status: 'PENDING' },
      data: { status, reviewerId: reviewer.id, reviewNote: note || null },
    });
    const current = await this.db.ticket.findUniqueOrThrow({ where: { id: ticket.id } });
    if (count !== 1) {
      throw new AppError(409, 'ticket_not_pending', `Ticket đang ở trạng thái ${current.status}, không thể duyệt/từ chối`);
    }
    return current;
  }

  private internalHeaders(): Record<string, string> {
    return { 'X-Internal-Secret': env('INTERNAL_SECRET'), ...forwardHeaders() };
  }

  /** Approval -> Agent: add a notification to the conversation (best effort). */
  private async notifyAgent(ticket: Ticket): Promise<void> {
    if (!ticket.conversationId) return;
    try {
      const resp = await fetch(`${env('AGENT_URL', 'http://agent:8000')}/internal/ticket-callback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...this.internalHeaders() },
        body: JSON.stringify(ticketOut(ticket)),
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    } catch (exc) {
      log.warn(`agent callback failed for ticket ${ticket.id}: ${String(exc)}`);
    }
  }

  /** Approve, then ask the Gateway to execute the tool call with a system token on behalf of the customer. */
  async approve(ticketId: string, reviewer: CurrentUser, note: string): Promise<Ticket> {
    const ticket = await this.claim(ticketId, 'APPROVED', reviewer, note);
    log.info(`ticket ${ticket.id} approved by ${reviewer.id}`);
    let result: Json;
    try {
      const resp = await fetch(`${env('GATEWAY_URL', 'http://gateway:8000')}/internal/execute-ticket/${ticket.id}`, {
        method: 'POST',
        headers: this.internalHeaders(),
        signal: AbortSignal.timeout(envNumber('EXECUTE_TIMEOUT_SECONDS', 15) * 1000),
      });
      result = (await resp.json()) as Json;
      if (!resp.ok && !('status' in result)) {
        result = { status: 'error', error: result.error ?? 'gateway_error', message: result.message ?? '' };
      }
    } catch (exc) {
      log.error(`execute-ticket ${ticket.id} failed: ${String(exc)}`);
      result = { status: 'error', error: 'gateway_unavailable', message: 'Không gọi được Gateway' };
    }
    const done = await this.db.ticket.update({
      where: { id: ticket.id },
      data: { result: result as Prisma.InputJsonValue, status: result.status === 'ok' ? 'EXECUTED' : 'FAILED' },
    });
    log.info(`ticket ${done.id} -> ${done.status}`);
    await this.notifyAgent(done);
    return done;
  }

  async reject(ticketId: string, reviewer: CurrentUser, note: string): Promise<Ticket> {
    const ticket = await this.claim(ticketId, 'REJECTED', reviewer, note);
    log.info(`ticket ${ticket.id} rejected by ${reviewer.id}`);
    await this.notifyAgent(ticket);
    return ticket;
  }
}
