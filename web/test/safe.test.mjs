import { test } from 'node:test';
import assert from 'node:assert';
import { safeSourceHref } from '../src/lib/safe.js';

test('allows http(s) URLs through', () => {
  assert.equal(safeSourceHref('https://example.com/a'), 'https://example.com/a');
  assert.equal(safeSourceHref('http://example.com/a'), 'http://example.com/a');
});

test('rejects dangerous schemes (no click-driven XSS via chip href)', () => {
  assert.equal(safeSourceHref('javascript:alert(1)'), null);
  assert.equal(safeSourceHref('data:text/html,<script>x</script>'), null);
  assert.equal(safeSourceHref('file:///etc/passwd'), null);
  assert.equal(safeSourceHref('vbscript:msgbox(1)'), null);
});

test('rejects non-strings and whitespace (falls back to button path)', () => {
  assert.equal(safeSourceHref(null), null);
  assert.equal(safeSourceHref(undefined), null);
  assert.equal(safeSourceHref(''), null);
  assert.equal(safeSourceHref('  '), null);
});
