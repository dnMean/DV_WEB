/** Tool registry built from the `x-agent-tool` extension in each service's OpenAPI (Swagger) document. */
import { log } from './common/logging';

type Json = Record<string, unknown>;
const HTTP_METHODS = new Set(['get', 'post', 'put', 'patch', 'delete']);
const RISKS = new Set(['low', 'medium', 'high']);

export class RegistryError extends Error {}

export interface ToolSpec {
  name: string;
  description: string;
  risk: 'low' | 'medium' | 'high';
  roles: string[];
  method: string;
  service_url: string;
  path: string;
  parameters: Json; // JSON Schema of the arguments object
  locations: Record<string, 'path' | 'query' | 'body'>;
  dedup_fields: string[] | null; // arguments that identify a duplicate approval request (null = all)
  precheck: string | null; // path on the same service validating a high risk call before a ticket is created
  confirm_args: string[] | null; // arguments that must appear literally in the user's own message
}

export const isWrite = (spec: ToolSpec) => spec.method !== 'GET';

export function toOpenAI(spec: ToolSpec) {
  return { type: 'function', function: { name: spec.name, description: spec.description, parameters: spec.parameters } };
}

/** Inline $ref, drop titles and OpenAPI-only keywords, collapse Optional (anyOf [X, null]) to X. */
function resolve(node: unknown, components: Json, seen: string[] = []): unknown {
  if (Array.isArray(node)) return node.map((x) => resolve(x, components, seen));
  if (!node || typeof node !== 'object') return node;
  const obj = node as Json;
  if (typeof obj.$ref === 'string') {
    const name = obj.$ref.split('/').pop()!;
    if (seen.includes(name)) return {};
    const { $ref: _ref, ...siblings } = obj;
    return resolve({ ...(components[name] as Json), ...siblings }, components, [...seen, name]);
  }
  const out: Json = {};
  for (const [k, v] of Object.entries(obj)) {
    if ((k === 'title' && typeof v === 'string') || k === 'nullable' || k === 'example') continue;
    out[k] = resolve(v, components, seen);
  }
  if (Array.isArray(out.anyOf)) {
    const options = (out.anyOf as Json[]).filter((o) => o.type !== 'null');
    if (options.length === 1 && options.length < (out.anyOf as Json[]).length) {
      const { anyOf: _anyOf, ...rest } = out;
      return { ...options[0], ...rest };
    }
  }
  if (out.default === null) delete out.default;
  return out;
}

export function buildTools(serviceUrl: string, openapi: Json): ToolSpec[] {
  const components = ((openapi.components as Json | undefined)?.schemas ?? {}) as Json;
  const tools: ToolSpec[] = [];
  for (const [path, item] of Object.entries((openapi.paths ?? {}) as Record<string, Json>)) {
    for (const [method, raw] of Object.entries(item)) {
      const op = raw as Json;
      if (!HTTP_METHODS.has(method) || !op['x-agent-tool']) continue;
      const ext = op['x-agent-tool'] as Json;
      const name = ext.name as string;
      if (!name || !RISKS.has(ext.risk as string) || !Array.isArray(ext.roles)) {
        throw new RegistryError(`invalid x-agent-tool on ${method.toUpperCase()} ${path} of ${serviceUrl}`);
      }
      const properties: Json = {};
      const required: string[] = [];
      const locations: ToolSpec['locations'] = {};
      const add = (arg: string, schema: Json, location: 'path' | 'query' | 'body', isRequired: boolean) => {
        if (arg in properties) throw new RegistryError(`tool ${name}: argument '${arg}' defined twice`);
        properties[arg] = schema;
        locations[arg] = location;
        if (isRequired) required.push(arg);
      };

      for (const p of [...((item.parameters as Json[]) ?? []), ...((op.parameters as Json[]) ?? [])]) {
        const param = resolve(p, components) as Json;
        if (param.in !== 'path' && param.in !== 'query') continue; // headers (Idempotency-Key, ...) are set by the gateway
        const schema = { ...((param.schema as Json) ?? {}) };
        if (param.description && !schema.description) schema.description = param.description;
        add(param.name as string, schema, param.in, param.in === 'path' || param.required === true);
      }
      const content = ((op.requestBody as Json | undefined)?.content as Json | undefined)?.['application/json'] as Json | undefined;
      if (content?.schema) {
        const body = resolve(content.schema, components) as Json;
        const bodyRequired = (body.required as string[]) ?? [];
        for (const [arg, schema] of Object.entries((body.properties ?? {}) as Json)) {
          add(arg, schema as Json, 'body', bodyRequired.includes(arg));
        }
      }
      const description = [op.summary, op.description]
        .filter((s): s is string => typeof s === 'string' && s.length > 0)
        .map((s) => s.trim().replace(/\.+$/, ''))
        .join('. ') + '.';
      tools.push({
        name, description, risk: ext.risk as ToolSpec['risk'], roles: [...(ext.roles as string[])],
        method: method.toUpperCase(), service_url: serviceUrl, path,
        parameters: { type: 'object', properties, required, additionalProperties: false },
        locations,
        dedup_fields: (ext.dedup_fields as string[]) ?? null,
        precheck: (ext.precheck as string) ?? null,
        confirm_args: (ext.confirm_args as string[]) ?? null,
      });
    }
  }
  return tools;
}

export function merge(byService: Map<string, ToolSpec[]>): Map<string, ToolSpec> {
  const tools = new Map<string, ToolSpec>();
  for (const [url, specs] of byService) {
    for (const spec of specs) {
      const other = tools.get(spec.name);
      if (other) throw new RegistryError(`duplicate tool name '${spec.name}' in ${url} and ${other.service_url}`);
      tools.set(spec.name, spec);
    }
  }
  return tools;
}

export class Registry {
  private byService = new Map<string, ToolSpec[]>();
  private tools = new Map<string, ToolSpec>();

  /**
   * Reload every service's OpenAPI. Unreachable services keep their previous tools.
   * Invalid or duplicate tool definitions throw when `strict` (startup); otherwise the old registry is kept.
   */
  async refresh(serviceUrls: string[], strict: boolean): Promise<void> {
    const byService = new Map(this.byService);
    for (const url of serviceUrls) {
      try {
        const resp = await fetch(`${url}/openapi.json`, { signal: AbortSignal.timeout(5000) });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        byService.set(url, buildTools(url, (await resp.json()) as Json));
      } catch (exc) {
        if (exc instanceof RegistryError) {
          if (strict) throw exc;
          log.error(`invalid tool definitions from ${url}; keeping previous`, exc);
        } else {
          log.warn(`cannot load OpenAPI from ${url}: ${String(exc)}`);
        }
      }
    }
    let tools: Map<string, ToolSpec>;
    try {
      tools = merge(byService);
    } catch (exc) {
      if (strict) throw exc;
      log.error('registry refresh rejected; keeping previous registry', exc);
      return;
    }
    this.byService = byService;
    this.tools = tools;
    log.info(`registry loaded ${tools.size} tools from ${byService.size} services`);
  }

  get(name: string): ToolSpec | undefined {
    return this.tools.get(name);
  }

  all(): ToolSpec[] {
    return [...this.tools.values()].sort((a, b) => a.name.localeCompare(b.name));
  }

  forRole(role: string): ToolSpec[] {
    return this.all().filter((t) => t.roles.includes(role));
  }
}
