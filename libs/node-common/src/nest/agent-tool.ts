import { ApiExtension } from '@nestjs/swagger';

export type Risk = 'low' | 'medium' | 'high';

export interface AgentToolOptions {
  /** High risk tools: arguments identifying "the same request" for approval de-duplication (default: all). */
  dedupFields?: string[];
  /** High risk tools: path on the same service the Gateway calls (user JWT, same body) before creating a ticket. */
  precheck?: string;
  /** Arguments whose value must appear literally in the end user's own chat message (checked by the Gateway). */
  confirmArgs?: string[];
}

/**
 * Declares an endpoint as an agent tool via the `x-agent-tool` OpenAPI extension; the Gateway builds its tool
 * registry from these, so the Swagger document and the tools can never drift apart.
 */
export function AgentTool(name: string, risk: Risk, roles: string[], opts: AgentToolOptions = {}) {
  const ext: Record<string, unknown> = { name, risk, roles };
  if (opts.dedupFields?.length) ext.dedup_fields = opts.dedupFields;
  if (opts.precheck) ext.precheck = opts.precheck;
  if (opts.confirmArgs?.length) ext.confirm_args = opts.confirmArgs;
  return ApiExtension('x-agent-tool', ext);
}
