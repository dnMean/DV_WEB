// Unit tests for the Gateway's pure logic (run on the compiled output: `npm test`).
const assert = require('node:assert/strict');
const { test } = require('node:test');

const { buildTools, merge, RegistryError } = require('../dist/registry');
const invoker = require('../dist/invoker');

// Shape produced by @nestjs/swagger: path/query params + a $ref'd body, x-agent-tool extension.
const OPENAPI = {
  paths: {
    '/orders/{order_id}/pay': {
      post: {
        summary: 'Thanh toán đơn hàng (giả lập)',
        description: 'Dùng khi khách yêu cầu thanh toán.',
        'x-agent-tool': { name: 'pay_order', risk: 'medium', roles: ['customer'], confirm_args: ['order_id'] },
        parameters: [
          { name: 'order_id', in: 'path', required: true, description: 'Mã đơn', schema: { type: 'integer', minimum: 1 } },
          { name: 'Idempotency-Key', in: 'header', required: false, schema: { type: 'string' } },
        ],
        requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/PayIn' } } } },
      },
    },
    '/orders': {
      get: {
        summary: 'Liệt kê đơn',
        'x-agent-tool': { name: 'list_my_orders', risk: 'low', roles: ['customer'] },
        parameters: [{ name: 'limit', in: 'query', required: false, schema: { type: 'integer', minimum: 1, maximum: 50, default: 20 } }],
      },
    },
    '/internal/reset': { post: { summary: 'not a tool' } },
  },
  components: {
    schemas: {
      PayIn: {
        type: 'object',
        title: 'PayIn',
        required: ['method'],
        properties: {
          method: { type: 'string', enum: ['CARD', 'BANK_TRANSFER', 'E_WALLET'] },
          address: { type: 'string', minLength: 10, nullable: true },
        },
      },
    },
  },
};

test('buildTools reads x-agent-tool, path/query/body arguments and inlines $ref', () => {
  const tools = Object.fromEntries(buildTools('http://order:8000', OPENAPI).map((t) => [t.name, t]));
  assert.deepEqual(Object.keys(tools).sort(), ['list_my_orders', 'pay_order']);
  const pay = tools.pay_order;
  assert.equal(pay.method, 'POST');
  assert.equal(pay.description, 'Thanh toán đơn hàng (giả lập). Dùng khi khách yêu cầu thanh toán.');
  assert.deepEqual(pay.locations, { order_id: 'path', method: 'body', address: 'body' });
  assert.deepEqual(pay.parameters.required, ['order_id', 'method']);
  assert.equal(pay.parameters.additionalProperties, false);
  assert.equal(pay.parameters.properties.order_id.description, 'Mã đơn');
  assert.equal('nullable' in pay.parameters.properties.address, false);
  assert.deepEqual(pay.confirm_args, ['order_id']);
  assert.equal(tools.list_my_orders.locations.limit, 'query');
});

test('invalid or duplicate tool definitions are rejected', () => {
  const bad = { paths: { '/x': { get: { 'x-agent-tool': { name: 'x', risk: 'extreme', roles: [] } } } } };
  assert.throws(() => buildTools('http://a', bad), RegistryError);
  const tools = buildTools('http://a', OPENAPI);
  assert.throws(() => merge(new Map([['http://a', tools], ['http://b', tools]])), /duplicate tool name/);
});

test('numeric strings from the LLM are coerced before validation', () => {
  const [pay] = buildTools('http://order:8000', OPENAPI).filter((t) => t.name === 'pay_order');
  assert.deepEqual(invoker.coerceArguments(pay, { order_id: ' 1002 ', method: 'CARD' }), { order_id: 1002, method: 'CARD' });
  assert.deepEqual(invoker.coerceArguments(pay, { order_id: 'abc' }), { order_id: 'abc' });
});

test('Ajv validation gives short, readable errors', () => {
  const [pay] = buildTools('http://order:8000', OPENAPI).filter((t) => t.name === 'pay_order');
  assert.equal(invoker.validateArguments(pay, { order_id: 1002, method: 'CARD' }), null);
  assert.match(invoker.validateArguments(pay, { order_id: 1002, method: 'COD' }), /^method: must be equal to one of the allowed values/);
  assert.match(invoker.validateArguments(pay, { order_id: 0, method: 'CARD' }), /^order_id: must be >= 1/);
  assert.match(invoker.validateArguments(pay, { method: 'CARD' }), /must have required property 'order_id'/);
  assert.match(invoker.validateArguments(pay, { order_id: 1, method: 'CARD', admin: true }), /additional properties 'admin'/);
});

test('idempotency keys ignore argument order but not conversation', () => {
  const a = invoker.idempotencyKey(1, 'cancel_order', { order_id: 1004, x: 1 }, 'c1');
  assert.equal(a, invoker.idempotencyKey(1, 'cancel_order', { x: 1, order_id: 1004 }, 'c1'));
  assert.notEqual(a, invoker.idempotencyKey(1, 'cancel_order', { order_id: 1004, x: 1 }, 'c2'));
  assert.equal(invoker.canonicalJson({ b: [1, { d: 1, c: 2 }], a: 'x' }), '{"a":"x","b":[1,{"c":2,"d":1}]}');
});
