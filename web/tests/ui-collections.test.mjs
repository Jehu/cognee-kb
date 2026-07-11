import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import {
  collectionControlsVisible,
  collectionLabelsEqual,
  filterSources,
  readCollectionVisibility,
  writeCollectionVisibility,
} from '../src/lib/collections.js';

test('collection labels compare like the backend for German case variants', () => {
  assert.equal(collectionLabelsEqual(' Straße ', 'STRASSE'), true);
  assert.equal(collectionLabelsEqual('Projekt  Alpha', 'projekt alpha'), true);
  assert.equal(collectionLabelsEqual('Alpha', 'Beta'), false);
});

beforeEach(() => {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (key) => store.get(key) || null,
    setItem: (key, value) => store.set(key, String(value)),
  };
});

test('collection visibility is versioned, per vault, defaults enabled, and recovers malformed data', () => {
  assert.equal(collectionControlsVisible('privat'), true);
  writeCollectionVisibility('privat', false);
  assert.equal(collectionControlsVisible('privat'), false);
  assert.equal(collectionControlsVisible('allgemein'), true);
  assert.deepEqual(readCollectionVisibility(), { version: 1, vaults: { privat: false } });

  localStorage.setItem('kb_collection_visibility', '{broken');
  assert.equal(collectionControlsVisible('privat'), true);
});

test('source type and collection filters intersect while collections use OR semantics', () => {
  const sources = [
    { source_id: '1', type: 'web', collection_ids: ['a'] },
    { source_id: '2', type: 'web', collection_ids: ['b'] },
    { source_id: '3', type: 'pdf', collection_ids: ['a', 'c'] },
  ];
  assert.deepEqual(filterSources(sources, 'web', ['a', 'c']).map((s) => s.source_id), ['1']);
  assert.deepEqual(filterSources(sources, '', ['b', 'c']).map((s) => s.source_id), ['2', '3']);
});

test('pages use shared collection controls and no longer expose Node-Set copy', async () => {
  const { readFile } = await import('node:fs/promises');
  const root = new URL('../', import.meta.url);
  const capture = await readFile(new URL('src/pages/index.astro', root), 'utf8');
  const sources = await readFile(new URL('src/pages/sources.astro', root), 'utf8');
  const chat = await readFile(new URL('src/pages/chat.astro', root), 'utf8');
  const settings = await readFile(new URL('src/pages/settings.astro', root), 'utf8');

  assert.doesNotMatch(capture, /Node-Set|node_set|ns-sug/);
  assert.match(capture, /collection_ids/);
  assert.match(sources, /Sammlungen bearbeiten/);
  assert.match(chat, /collection_ids/);
  assert.match(chat, /scopeLabels/);
  assert.match(settings, /Sammlungen anzeigen/);
  assert.match(settings, /Archivierte Sammlungen/);
});
