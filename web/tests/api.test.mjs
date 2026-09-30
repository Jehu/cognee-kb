import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import {
  createCollection,
  initVaultSelect,
  loadCollections,
  loadVaults,
  reassignSourceCollections,
} from '../src/lib/api.js';

function makeSelect() {
  return {
    disabled: false,
    innerHTML: '',
    options: [],
    value: '',
    dataset: {},
    appendChild(option) {
      this.options.push(option);
    },
  };
}

beforeEach(() => {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (key) => store.get(key) || null,
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
  globalThis.document = {
    createElement(tag) {
      assert.match(tag, /^(option|optgroup)$/);
      return {
        value: '',
        textContent: '',
        label: '',
        children: [],
        appendChild(child) {
          this.children.push(child);
        },
      };
    },
  };
});

test('initVaultSelect disables vault selection when the gateway rejects missing auth', async () => {
  globalThis.fetch = async () => ({
    status: 401,
    ok: false,
    json: async () => ({ detail: 'Fehlendes oder ungültiges Token' }),
  });

  const select = makeSelect();
  const state = await initVaultSelect(select);

  assert.equal(state.ok, false);
  assert.equal(state.reason, 'auth');
  assert.equal(select.disabled, true);
  assert.equal(select.options.length, 1);
  assert.equal(select.options[0].value, '');
  assert.equal(select.options[0].textContent, 'Token in Einstellungen setzen');
});

test('loadVaults keeps allgemein in the offline fallback list', async () => {
  globalThis.fetch = async () => {
    throw new Error('offline');
  };

  const state = await loadVaults();

  assert.equal(state.ok, true);
  assert.equal(state.source, 'fallback');
  assert.deepEqual(state.names, ['privat', 'allgemein', 'business-ki', 'business-mwe']);
});

test('initVaultSelect groups API vaults by wall and keeps the wall visible in option labels', async () => {
  globalThis.fetch = async () => ({
    status: 200,
    ok: true,
    json: async () => [
      { name: 'privat', instance: 'local' },
      { name: 'allgemein', instance: 'cloud' },
      { name: 'business-ki', instance: 'cloud' },
    ],
  });

  const select = makeSelect();
  const state = await initVaultSelect(select);

  assert.equal(state.ok, true);
  assert.equal(select.disabled, false);
  assert.deepEqual(select.options.map((group) => group.label), ['local', 'cloud']);
  assert.deepEqual(select.options[0].children.map((opt) => [opt.value, opt.textContent]), [
    ['privat', 'privat (local)'],
  ]);
  assert.deepEqual(select.options[1].children.map((opt) => [opt.value, opt.textContent]), [
    ['allgemein', 'allgemein (cloud)'],
    ['business-ki', 'business-ki (cloud)'],
  ]);
});

test('collection API helpers encode vaults and send stable IDs', async () => {
  const calls = [];
  globalThis.fetch = async (path, options = {}) => {
    calls.push([path, options]);
    return { status: 200, ok: true, json: async () => ({ collections: [{ id: 'c1' }] }) };
  };

  assert.deepEqual(await loadCollections('business ki', true), [{ id: 'c1' }]);
  await createCollection('business ki', ' Projekt ');
  await reassignSourceCollections('business ki', 'source/1', ['c1']);

  assert.equal(calls[0][0], '/api/collections/business%20ki?include_archived=true');
  assert.deepEqual(JSON.parse(calls[1][1].body), { label: ' Projekt ' });
  assert.equal(calls[2][0], '/api/sources/business%20ki/source%2F1/collections');
  assert.deepEqual(JSON.parse(calls[2][1].body), { collection_ids: ['c1'] });
});

test('uploadDocument sends multipart FormData with Bearer and no explicit content type', async () => {
  localStorage.setItem('kb_token', 'tok');
  let captured = null;
  globalThis.fetch = async (path, options = {}) => {
    captured = { path, options };
    return { status: 202, ok: true, json: async () => ({ job_id: 7, vault: 'privat', kind: 'upload' }) };
  };

  const { uploadDocument } = await import('../src/lib/api.js');
  const file = new File([new Uint8Array([1, 2, 3])], 'note.md', { type: 'text/markdown' });
  const result = await uploadDocument('privat', file, ['c1', 'c2']);

  assert.deepEqual(result, { job_id: 7, vault: 'privat', kind: 'upload' });
  assert.equal(captured.path, '/api/uploads');
  assert.equal(captured.options.method, 'POST');
  assert.equal(captured.options.headers.Authorization, 'Bearer tok');
  assert.equal(captured.options.headers['Content-Type'], undefined, 'multipart boundary must come from the browser');
  assert.ok(captured.options.body instanceof FormData);
  assert.equal(captured.options.body.get('vault'), 'privat');
  assert.equal(captured.options.body.get('file'), file);
  assert.deepEqual(JSON.parse(captured.options.body.get('collection_ids')), ['c1', 'c2']);
});

test('api still sets JSON content type for string bodies', async () => {
  localStorage.setItem('kb_token', 'tok');
  let headers = null;
  globalThis.fetch = async (_path, options = {}) => {
    headers = options.headers;
    return { status: 202, ok: true, json: async () => ({}) };
  };

  const { api } = await import('../src/lib/api.js');
  await api('/api/ingest', { method: 'POST', body: JSON.stringify({ vault: 'privat', content: 'x' }) });
  assert.equal(headers['Content-Type'], 'application/json');
});

test('uploadDocument surfaces server validation detail as ApiError', async () => {
  localStorage.setItem('kb_token', 'tok');
  globalThis.fetch = async () => ({
    status: 413,
    ok: false,
    json: async () => ({ detail: 'Datei überschreitet 20 MiB' }),
  });

  const { uploadDocument, ApiError } = await import('../src/lib/api.js');
  const file = new File([new Uint8Array(21 * 1024 * 1024)], 'big.pdf', { type: 'application/pdf' });
  await assert.rejects(
    uploadDocument('privat', file, []),
    (e) => e instanceof ApiError && e.status === 413 && /20 MiB/.test(e.message),
  );
});

test('validateUploadFile rejects unsupported, empty, and oversized files before transfer', async () => {
  const { validateUploadFile, UPLOAD_MAX_BYTES } = await import('../src/lib/api.js');
  const ok = new File([new Uint8Array([1])], 'Note.PDF');
  assert.equal(validateUploadFile(ok), '');
  assert.equal(validateUploadFile(new File([new Uint8Array([1])], 'a.md')), '');
  assert.equal(validateUploadFile(new File([new Uint8Array([1])], 'a.txt')), '');

  assert.match(validateUploadFile(new File([new Uint8Array([1])], 'tool.exe')), /Nicht unterstütztes Format/);
  assert.match(validateUploadFile(new File([new Uint8Array([1])], 'noext')), /Nicht unterstütztes Format/);
  assert.match(validateUploadFile(new File([], 'empty.md')), /leer/);

  const big = new File([new Uint8Array(UPLOAD_MAX_BYTES + 1)], 'big.pdf');
  assert.match(validateUploadFile(big), /zu groß/);
  assert.match(validateUploadFile(big), /20 MiB/);
});
