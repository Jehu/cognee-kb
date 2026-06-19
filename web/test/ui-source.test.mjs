import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const root = new URL('../', import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), 'utf8');
}

test('ingest page exposes a compact capture flow with advanced metadata and job steps', async () => {
  const html = await source('src/pages/index.astro');

  assert.match(html, /class="page-intro"/);
  assert.match(html, /<details class="advanced-fields"/);
  assert.match(html, /list="node-set-suggestions"/);
  assert.match(html, /id="node-set-suggestions"/);
  assert.match(html, /loadNodeSets/);
  assert.match(html, /id="job-steps"/);
  assert.match(html, /\.job-steps\.hidden/);
  assert.match(html, /Quelle speichern/);
});

test('chat page has a useful empty state with sample questions', async () => {
  const html = await source('src/pages/chat.astro');

  assert.match(html, /id="empty-state"/);
  assert.match(html, /class="sample-question"/);
  assert.match(html, /data-question=/);
});

test('chat page renders dynamic messages with global readable bubble styles', async () => {
  const html = await source('src/pages/chat.astro');

  assert.match(html, /<style is:global>/);
  assert.match(html, /chat-message/);
  assert.match(html, /message-bubble/);
  assert.match(html, /message-header/);
  assert.match(html, /role-badge/);
  assert.match(html, /message-body/);
});

test('settings page can reveal the token and re-test the connection', async () => {
  const html = await source('src/pages/settings.astro');

  assert.match(html, /id="toggle-token"/);
  assert.match(html, /id="test-connection"/);
  assert.match(html, /Token anzeigen/);
  assert.match(html, /Status neu testen/);
});

test('base layout provides mobile app-style navigation and wall badges', async () => {
  const html = await source('src/layouts/Base.astro');

  assert.match(html, /class="nav-icon"/);
  assert.match(html, /@media \(max-width: 520px\)/);
  assert.match(html, /\.wall-badge/);
});
