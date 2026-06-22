import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import { initVaultSelect, loadVaults } from '../src/lib/api.js';

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
