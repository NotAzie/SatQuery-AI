import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { apiNotFoundPlugin } from '../../server/standalone/api-not-found.js';

function middleware() {
  let handler;
  apiNotFoundPlugin().configureServer({
    middlewares: {
      use(path, next) {
        assert.equal(path, '/api');
        handler = next;
      },
    },
  });
  return handler;
}

describe('Platform API pass-through', () => {
  it('passes Platform v1 routes to the host proxy', () => {
    const handler = middleware();
    let passed = false;
    handler(
      { url: '/v1/investigations' },
      {},
      () => {
        passed = true;
      },
    );
    assert.equal(passed, true);
  });

  it('keeps the Earth runtime 404 for unknown API routes', () => {
    const handler = middleware();
    let status;
    let body;
    handler(
      { url: '/unknown' },
      {
        writeHead(code) {
          status = code;
        },
        end(value) {
          body = value;
        },
      },
      () => assert.fail('unknown routes must not reach the Platform proxy'),
    );
    assert.equal(status, 404);
    assert.deepEqual(JSON.parse(body), { error: 'Unknown API route' });
  });
});
