import { test } from 'node:test';
import assert from 'node:assert';
import { openBlobInNewTab } from '../src/lib/api.js';

// api.js greift auf window/URL/alert/setTimeout nur zur Laufzeit zu — wir
// mocken die Globals für diesen Test und stellen sie danach wieder her.

function withGlobals(stubs, fn) {
  const saved = {};
  const keys = Object.keys(stubs);
  for (const k of keys) {
    saved[k] = globalThis[k];
    globalThis[k] = stubs[k];
  }
  // Reference: window kann auch über globalThis angesprochen werden.
  if (stubs.window) globalThis.window = stubs.window;
  try {
    return fn();
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete globalThis[k];
      else globalThis[k] = saved[k];
    }
  }
}

test('opens the blob URL and revokes it when the timer fires', () => {
  const revoked = [];
  let opened = null;
  let revokeFn = null;
  withGlobals(
    {
      URL: {
        createObjectURL: () => 'blob:fake',
        revokeObjectURL: (u) => revoked.push(u),
      },
      window: { open: (u) => { opened = u; return { closed: false }; } },
      setTimeout: (fn) => { revokeFn = fn; },
    },
    () => {
      openBlobInNewTab(new Blob(['x']));
      assert.equal(opened, 'blob:fake');
      assert.equal(revoked.length, 0, 'not revoked immediately');
      revokeFn(); // URL-Stub ist hier noch aktiv
      assert.deepEqual(revoked, ['blob:fake'], 'revoked when the timer fires');
    },
  );
});

test('alerts when the popup is blocked (window.open returns null)', () => {
  let alerted = '';
  withGlobals(
    {
      URL: { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} },
      window: { open: () => null }, // blockiert
      setTimeout: () => {},
      alert: (m) => { alerted = m; },
    },
    () => openBlobInNewTab(new Blob(['x'])),
  );
  assert.match(alerted, /blockiert/i);
});
