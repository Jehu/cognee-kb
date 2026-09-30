import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const root = new URL('../', import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), 'utf8');
}

test('ingest page exposes a compact capture flow with metadata and job steps', async () => {
  const html = await source('src/pages/index.astro');
  assert.match(html, /class="page-intro"/);
  assert.match(html, /id="capture-collections"/);
  assert.match(html, /id="steps"/);
  assert.match(html, /class="job-steps hidden"/);
  assert.match(html, /Speichern/);
  assert.match(html, /vault-hint/);
});

test('ingest page offers an exclusive file mode with format and size hints', async () => {
  const html = await source('src/pages/index.astro');
  assert.match(html, /data-mode="text"/);
  assert.match(html, /data-mode="file"/);
  assert.match(html, /type="file"/);
  assert.match(html, /accept="\.pdf,\.md,\.txt"/);
  assert.match(html, /20 MiB/);
  assert.match(html, /validateUploadFile/);
  assert.match(html, /uploadDocument/);
  // File mode must not demand text content and vice versa.
  assert.match(html, /content\.required = !isFile/);
  // Job polling goes through the authenticated API helper, not bare fetch.
  assert.doesNotMatch(html, /fetch\(`\/api\/jobs/);
  assert.match(html, /api\(`\/api\/jobs\//);
});

test('chat page has a useful empty state with sample questions', async () => {
  const html = await source('src/pages/chat.astro');
  assert.match(html, /id="empty"/);
  assert.match(html, /class="sample-q"/);
  assert.match(html, /data-q=/);
});

test('chat page renders dynamic messages with readable bubble styles', async () => {
  const html = await source('src/pages/chat.astro');
  assert.match(html, /chat-history/);
  assert.match(html, /msg-bubble/);
  assert.match(html, /msg-role/);
});

test('chat page renders citations and knowledge gaps accessibly', async () => {
  const html = await source('src/pages/chat.astro');
  assert.match(html, /citation-list/);
  assert.match(html, /gap-list/);
  assert.match(html, /role = 'status'/);
  assert.match(html, /citations: r\.citations/);
  assert.match(html, /gaps: r\.gaps/);
});

test('settings page can show token, diagnostics, and save', async () => {
  const html = await source('src/pages/settings.astro');
  assert.match(html, /id="token"/);
  assert.match(html, /id="diag"/);
  assert.match(html, /diag-card/);
  assert.match(html, /Status testen/);
});

test('base layout provides mobile tabbar and desktop sidebar with wall dots', async () => {
  const html = await source('src/layouts/Base.astro');
  assert.match(html, /class="tabbar"/);
  assert.match(html, /@media \(min-width: 880px\)/);
  assert.match(html, /wall-dot/);
  assert.match(html, /id="vault-ctx"/);
});
