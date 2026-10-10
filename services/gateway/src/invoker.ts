/** Argument handling (Ajv) and service calls for `POST /invoke` (spec 7.3). */
import { createHash } from 'node:crypto';

import Ajv, { ValidateFunction } from 'ajv';

import { log } from './common/logging';
import { ToolSpec, isWrite } from './registry';

type Json = Record<string, unknown>;
export type Result = Json & { status: string };

const ajv = new Ajv({ allErrors: true, strict: false });
const validators = new WeakMap<ToolSpec, ValidateFunction>();

export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonicalJson((value as Json)[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export function idempotencyKey(userId: number, tool: string, args: Json, conversationId: string): string {
  return createHash('sha256').update(`${userId}|${tool}|${canonicalJson(args)}|${conversationId}`).digest('hex');
}

/** LLMs often send numbers as strings ("1002"); convert those for integer/number params. */
export function coerceArguments(spec: ToolSpec, args: Json): Json {
  const props = (spec.parameters.properties ?? {}) as Record<string, Json>;
  const out: Json = { ...args };
  for (const [name, value] of Object.entries(args)) {
    if (typeof value !== 'string') continue;
    const type = props[name]?.type;
    const v = value.trim();
    if (type === 'integer' && /^-?\d+$/.test(v)) out[name] = Number(v);
    else if (type === 'number' && /^-?\d+(\.\d+)?$/.test(v)) out[name] = Number(v);
  }
  return out;
}

/** JSON Schema check (Ajv). Short, LLM-readable error message, or null when valid. */
export function validateArguments(spec: ToolSpec, args: Json): string | null {
  let validate = validators.get(spec);
  if (!validate) {
    validate = ajv.compile(spec.parameters);
    validators.set(spec, validate);
  }
  if (validate(args)) return null;
  return (validate.errors ?? []).slice(0, 3).map((e) => {
    const where = e.instancePath.replace(/^\//, '').replace(/\//g, '.');
    const extra = e.params.additionalProperty ? ` '${e.params.additionalProperty}'` : '';
    return where ? `${where}: ${e.message}${extra}` : `${e.message}${extra}`;
  }).join('; ');
}

function buildRequest(spec: ToolSpec, args: Json): { url: string; body: Json | undefined } {
  const path = spec.path.replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(String(args[k])));
  const query = new URLSearchParams();
  const body: Json = {};
  for (const [k, v] of Object.entries(args)) {
    if (spec.locations[k] === 'query' && v !== undefined && v !== null) query.set(k, String(v));
    if (spec.locations[k] === 'body') body[k] = v;
  }
  const qs = query.toString();
  const hasBody = Object.values(spec.locations).includes('body');
  return { url: spec.service_url + path + (qs ? `?${qs}` : ''), body: hasBody ? body : undefined };
}

export function error(code: string, message: string, extra: Json = {}): Result {
  return { status: 'error', error: code, message, ...extra };
}

function truncate(data: unknown, maxChars: number): [unknown, boolean] {
  const text = JSON.stringify(data);
  return text.length <= maxChars ? [data, false] : [text.slice(0, maxChars), true];
}

async function normalizeResponse(resp: Response, maxChars: number): Promise<Result> {
  const text = await resp.text();
  let payload: unknown = text;
  try {
    payload = JSON.parse(text);
  } catch {
    // keep text
  }
  if (resp.ok) {
    const [data, truncated] = truncate(payload, maxChars);
    return truncated ? { status: 'ok', data, truncated: true } : { status: 'ok', data };
  }
  if (payload && typeof payload === 'object' && 'error' in payload) {
    const { error: code, message, ...extra } = payload as Json;
    return error(String(code), String(message ?? ''), { http_status: resp.status, ...extra });
  }
  return error('service_error', String(payload).slice(0, 300), { http_status: resp.status });
}

function send(spec: ToolSpec, method: string, url: string, body: Json | undefined, headers: Record<string, string>, timeoutMs: number) {
  return fetch(url, {
    method,
    headers: body === undefined ? headers : { ...headers, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
}

/** Ask the service whether a high risk call would be accepted. null = OK, else an error result. */
export async function precheck(spec: ToolSpec, args: Json, headers: Record<string, string>, timeoutMs: number): Promise<Result | null> {
  const { url, body } = buildRequest({ ...spec, path: spec.precheck! }, args);
  try {
    const resp = await send(spec, 'POST', url, body, headers, timeoutMs);
    return resp.ok ? null : normalizeResponse(resp, 4000);
  } catch (exc) {
    return error('service_unavailable', `Không kiểm tra được yêu cầu: ${(exc as Error).name}`);
  }
}

/** Execute the tool's HTTP call. Read tools are retried once on network errors / 5xx. */
export async function callService(
  spec: ToolSpec, args: Json, headers: Record<string, string>, timeoutMs: number, maxChars: number,
): Promise<Result> {
  const { url, body } = buildRequest(spec, args);
  const attempts = isWrite(spec) ? 1 : 2;
  for (let attempt = 1; ; attempt++) {
    let resp: Response;
    try {
      resp = await send(spec, spec.method, url, body, headers, timeoutMs);
    } catch (exc) {
      if (attempt < attempts) continue;
      if ((exc as Error).name === 'TimeoutError') return error('timeout', `Service không phản hồi trong ${timeoutMs / 1000}s`);
      return error('service_unavailable', `Không kết nối được service: ${(exc as Error).name}`);
    }
    if (resp.status >= 500 && attempt < attempts) {
      log.warn(`${spec.name} returned ${resp.status}, retrying`);
      continue;
    }
    return normalizeResponse(resp, maxChars);
  }
}
